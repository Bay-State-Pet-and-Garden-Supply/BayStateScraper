"""
Supabase Realtime subscription manager for scrape job notifications.

Features:
- Subscribe to scrape_jobs INSERT events
- Track runner presence (online/offline status)
- Broadcast job progress, logs, and heartbeats to admin dashboard
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from realtime import AsyncRealtimeClient, ClientOptions, create_client

logger = logging.getLogger(__name__)

# Reconnection configuration
RECONNECT_DELAYS = [1, 2, 4, 8, 16, 32]
MAX_RECONNECT_ATTEMPTS = 10

# Broadcast channel names
CHANNEL_RUNNER_PRESENCE = "runner-presence"
CHANNEL_JOB_BROADCAST = "job-broadcast"
CHANNEL_RUNNER_LOGS = "runner-logs"


class RealtimeManager:
    """
    Manages Supabase Realtime WebSocket connections for job notifications.

    Features:
    - Async WebSocket connection management
    - Automatic reconnection with exponential backoff
    - Subscribe to scrape_jobs INSERT events with status=eq.pending filter
    - Thread-safe job queuing via asyncio.Queue
    - Graceful shutdown via asyncio.Event
    - Presence tracking for runner online/offline status
    - Broadcast capabilities for job progress, logs, and heartbeats
    """

    RECONNECT_DELAYS = RECONNECT_DELAYS
    MAX_RECONNECT_ATTEMPTS = MAX_RECONNECT_ATTEMPTS

    def __init__(
        self,
        supabase_url: str,
        service_key: str,
        runner_name: str,
        runner_id: str | None = None,
    ):
        """
        Initialize the RealtimeManager.

        Args:
            supabase_url: Full Supabase project URL (e.g., https://xyz.supabase.co)
            service_key: Supabase service role key or anon key
            runner_name: Unique identifier for this runner instance
            runner_id: Optional runner ID for presence tracking
        """
        self.supabase_url = supabase_url
        self.service_key = service_key
        self.runner_name = runner_name
        self.runner_id = runner_id or runner_name

        self.client: AsyncRealtimeClient | None = None
        self._connected = False
        self._reconnect_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._pending_jobs: asyncio.Queue = asyncio.Queue()
        self._job_callback: Callable[[dict], None] | None = None

        # Presence tracking
        self._presence_task: asyncio.Task | None = None
        self._presence_interval = 30  # seconds between presence updates

        # Broadcast channels
        self._broadcast_channel = None
        self._presence_channel = None

    @property
    def is_connected(self) -> bool:
        """Check if the WebSocket connection is active."""
        return self._connected

    async def connect(self) -> bool:
        """
        Establish WebSocket connection to Supabase Realtime.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            opts = ClientOptions(
                realtime={
                    "heartbeat_interval": 30,
                    "timeout": 10,
                }
            )

            self.client = await create_client(
                self.supabase_url,
                self.service_key,
                opts,
                is_async=True,
            )

            self._connected = True
            logger.info(f"[{self.runner_name}] Connected to Supabase Realtime")
            return True

        except Exception as e:
            logger.error(
                f"[{self.runner_name}] Failed to connect to Supabase Realtime: {e}"
            )
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """
        Gracefully close WebSocket connection and stop reconnection.

        Sets shutdown event, cancels reconnection task, and closes all channel
        subscriptions.
        """
        logger.info(f"[{self.runner_name}] Disconnecting from Supabase Realtime...")

        # Signal shutdown to stop reconnection attempts
        self._shutdown_event.set()

        # Stop presence tracking
        if self._presence_task and not self._presence_task.done():
            self._presence_task.cancel()
            try:
                await self._presence_task
            except asyncio.CancelledError:
                pass

        # Cancel any pending reconnection task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Close all channel subscriptions
        if self.client:
            channels = self.client.get_channels()
            for channel in channels:
                await channel.unsubscribe()
            await self.client.close()

        self._connected = False
        logger.info(f"[{self.runner_name}] Disconnected from Supabase Realtime")

    async def subscribe_to_jobs(self, callback: Callable[[dict], None]) -> None:
        """
        Subscribe to INSERT events on the scrape_jobs table.

        Filters for jobs where status='pending'. When a matching INSERT is
        detected, the job data is placed on the internal queue and the callback
        is invoked.

        Args:
            callback: Async or sync callable that accepts job data dict
        """
        if not self.client:
            logger.error(
                f"[{self.runner_name}] Cannot subscribe: client not initialized"
            )
            return

        self._job_callback = callback

        channel = self.client.channel(f"runner:{self.runner_name}")

        channel.on_postgres_changes(
            event="INSERT",
            schema="public",
            table="scrape_jobs",
            filter="status=eq.pending",
            callback=self._handle_job_insert,
        )

        await channel.subscribe()
        logger.info(
            f"[{self.runner_name}] Subscribed to scrape_jobs INSERT events "
            "(status=eq.pending)"
        )

    async def _handle_job_insert(self, payload: dict) -> None:
        """
        Handle INSERT event from scrape_jobs table.

        Args:
            payload: Realtime payload containing 'new' key with inserted row
        """
        try:
            job_data = payload.get("new")
            if not job_data:
                logger.warning(
                    f"[{self.runner_name}] Received INSERT with no 'new' data"
                )
                return

            await self._pending_jobs.put(job_data)
            logger.info(
                f"[{self.runner_name}] Queued pending job: {job_data.get('job_id')}"
            )

            # Invoke callback if registered
            if self._job_callback:
                try:
                    if asyncio.iscoroutinefunction(self._job_callback):
                        await self._job_callback(job_data)
                    else:
                        self._job_callback(job_data)
                except Exception as e:
                    logger.error(f"[{self.runner_name}] Job callback error: {e}")

        except Exception as e:
            logger.error(f"[{self.runner_name}] Error handling job INSERT: {e}")

    async def enable_presence(self) -> bool:
        """
        Enable presence tracking for this runner.

        Tracks runner online/offline status in the admin dashboard.

        Returns:
            True if presence was enabled successfully
        """
        if not self.client:
            logger.error(
                f"[{self.runner_name}] Cannot enable presence: client not initialized"
            )
            return False

        try:
            self._presence_channel = self.client.channel(CHANNEL_RUNNER_PRESENCE)

            # Set up presence tracking
            self._presence_channel.on_presence(
                event="sync",
                callback=self._handle_presence_sync,
            )
            self._presence_channel.on_presence(
                event="join",
                callback=self._handle_presence_join,
            )
            self._presence_channel.on_presence(
                event="leave",
                callback=self._handle_presence_leave,
            )

            await self._presence_channel.subscribe()
            logger.info(f"[{self.runner_name}] Presence channel subscribed")

            # Track self as online
            await self._presence_channel.track(
                {
                    "runner_id": self.runner_id,
                    "runner_name": self.runner_name,
                    "status": "online",
                    "last_seen": time.time(),
                }
            )
            logger.info(f"[{self.runner_name}] Presence tracking enabled")

            # Start background task to send periodic heartbeats
            self._presence_task = asyncio.create_task(self._presence_heartbeat_loop())

            return True

        except Exception as e:
            logger.error(f"[{self.runner_name}] Failed to enable presence: {e}")
            return False

    async def _presence_heartbeat_loop(self) -> None:
        """Send periodic presence updates to keep runner marked as online."""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self._presence_interval)

                if self._presence_channel and self._connected:
                    try:
                        await self._presence_channel.track(
                            {
                                "runner_id": self.runner_id,
                                "runner_name": self.runner_name,
                                "status": "online",
                                "last_seen": time.time(),
                            }
                        )
                        logger.debug(f"[{self.runner_name}] Presence heartbeat sent")
                    except Exception as e:
                        logger.warning(
                            f"[{self.runner_name}] Failed to send presence heartbeat: {e}"
                        )

        except asyncio.CancelledError:
            logger.info(f"[{self.runner_name}] Presence heartbeat loop cancelled")
        except Exception as e:
            logger.error(f"[{self.runner_name}] Presence heartbeat error: {e}")

    def _handle_presence_sync(self, payload: dict) -> None:
        """Handle presence sync event."""
        logger.debug(f"[{self.runner_name}] Presence sync: {payload}")

    def _handle_presence_join(self, payload: dict) -> None:
        """Handle presence join event."""
        logger.debug(f"[{self.runner_name}] Presence join: {payload}")

    def _handle_presence_leave(self, payload: dict) -> None:
        """Handle presence leave event."""
        logger.debug(f"[{self.runner_name}] Presence leave: {payload}")

    async def enable_broadcast(self) -> bool:
        """
        Enable broadcast channels for sending job progress and logs.

        Returns:
            True if broadcast was enabled successfully
        """
        if not self.client:
            logger.error(
                f"[{self.runner_name}] Cannot enable broadcast: client not initialized"
            )
            return False

        try:
            # Job progress broadcast channel
            self._broadcast_channel = self.client.channel(CHANNEL_JOB_BROADCAST)

            await self._broadcast_channel.subscribe()
            logger.info(f"[{self.runner_name}] Broadcast channel enabled")

            return True

        except Exception as e:
            logger.error(f"[{self.runner_name}] Failed to enable broadcast: {e}")
            return False

    async def broadcast_job_progress(
        self,
        job_id: str,
        status: str,
        progress: int,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        """
        Broadcast job progress to the admin dashboard.

        Args:
            job_id: The job ID being processed
            status: Current status (started, running, completed, failed)
            progress: Progress percentage (0-100)
            message: Optional status message
            details: Optional additional details
        """
        if not self._broadcast_channel or not self._connected:
            return

        try:
            await self._broadcast_channel.send(
                type="broadcast",
                event="job_progress",
                payload={
                    "job_id": job_id,
                    "runner_id": self.runner_id,
                    "runner_name": self.runner_name,
                    "status": status,
                    "progress": progress,
                    "message": message,
                    "details": details or {},
                    "timestamp": time.time(),
                },
            )
            logger.debug(
                f"[{self.runner_name}] Broadcast job progress: {job_id} {status}"
            )
        except Exception as e:
            logger.warning(
                f"[{self.runner_name}] Failed to broadcast job progress: {e}"
            )

    async def broadcast_job_log(
        self,
        job_id: str,
        level: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        """
        Broadcast a log message to the admin dashboard.

        Args:
            job_id: The job ID this log is for
            level: Log level (info, warning, error, debug)
            message: Log message
            details: Optional additional details
        """
        if not self._broadcast_channel or not self._connected:
            return

        try:
            await self._broadcast_channel.send(
                type="broadcast",
                event="runner_log",
                payload={
                    "job_id": job_id,
                    "runner_id": self.runner_id,
                    "runner_name": self.runner_name,
                    "level": level,
                    "message": message,
                    "details": details or {},
                    "timestamp": time.time(),
                },
            )
            logger.debug(f"[{self.runner_name}] Broadcast log: {level} {message}")
        except Exception as e:
            logger.warning(f"[{self.runner_name}] Failed to broadcast log: {e}")

    async def broadcast_runner_status(
        self,
        status: str,
        details: dict | None = None,
    ) -> None:
        """
        Broadcast runner status update (e.g., starting, stopping, error).

        Args:
            status: Status string (starting, stopping, error, idle)
            details: Optional additional details
        """
        if not self._broadcast_channel or not self._connected:
            return

        try:
            await self._broadcast_channel.send(
                type="broadcast",
                event="runner_status",
                payload={
                    "runner_id": self.runner_id,
                    "runner_name": self.runner_name,
                    "status": status,
                    "details": details or {},
                    "timestamp": time.time(),
                },
            )
            logger.debug(f"[{self.runner_name}] Broadcast runner status: {status}")
        except Exception as e:
            logger.warning(
                f"[{{self.runner_name}}] Failed to broadcast runner status: {e}"
            )

    async def get_pending_job(self) -> dict | None:
        """
        Get the next pending job from the queue.

        Returns:
            Job data dict, or None if queue is empty
        """
        try:
            return await asyncio.wait_for(self._pending_jobs.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    def clear_pending_jobs(self) -> None:
        """Clear all pending jobs from the queue."""
        while not self._pending_jobs.empty():
            try:
                self._pending_jobs.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info(f"[{self.runner_name}] Cleared pending jobs queue")

    async def _auto_reconnect(self) -> None:
        """
        Attempt reconnection with exponential backoff.

        Stops when:
        - Connection succeeds
        - Shutdown event is set
        - All reconnect attempts exhausted
        """
        logger.info(f"[{self.runner_name}] Starting auto-reconnect sequence...")

        for attempt, delay in enumerate(self.RECONNECT_DELAYS, start=1):
            if self._shutdown_event.is_set():
                logger.info(
                    f"[{self.runner_name}] Shutdown requested, skipping reconnect"
                )
                return

            logger.info(
                f"[{self.runner_name}] Reconnect attempt {attempt}/{len(self.RECONNECT_DELAYS)} "
                f"in {delay}s"
            )

            await asyncio.sleep(delay)

            if await self.connect():
                logger.info(f"[{self.runner_name}] Reconnection successful!")
                return

        logger.error(
            f"[{self.runner_name}] Max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}) exhausted"
        )
        self._connected = False

    def start_reconnection_loop(self) -> None:
        """Start the background auto-reconnection loop."""
        if self._reconnect_task and not self._reconnect_task.done():
            logger.warning(f"[{self.runner_name}] Reconnection loop already running")
            return

        self._reconnect_task = asyncio.create_task(self._auto_reconnect())
        logger.info(f"[{self.runner_name}] Started reconnection loop")

    async def wait_for_job(self, timeout: float | None = None) -> dict | None:
        """
        Wait for a pending job to arrive in the queue.

        Args:
            timeout: Maximum seconds to wait, None for indefinite

        Returns:
            Job data dict, or None if timeout reached
        """
        try:
            if timeout:
                return await asyncio.wait_for(self._pending_jobs.get(), timeout=timeout)
            else:
                return await self._pending_jobs.get()
        except asyncio.TimeoutError:
            return None

    def queue_size(self) -> int:
        """Return the current number of pending jobs in queue."""
        return self._pending_jobs.qsize()
