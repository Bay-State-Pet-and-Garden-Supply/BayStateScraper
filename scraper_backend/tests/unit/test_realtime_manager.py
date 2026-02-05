"""
Unit tests for RealtimeManager - Supabase Realtime WebSocket subscription manager.

Tests cover:
- Connection establishment and timeout
- Job INSERT event handling and callback invocation
- Subscription filter configuration
- Graceful disconnection and cleanup
- Automatic reconnection with exponential backoff
- Job queue operations
- Shutdown event handling
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper_backend.core.realtime_manager import RealtimeManager

logger = logging.getLogger(__name__)


class TestRealtimeManagerConnection:
    """Tests for connection establishment and management."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )

    @pytest.mark.asyncio
    async def test_connection_establishes(self, mock_realtime_client):
        """Runner connects to Supabase Realtime within 5 seconds."""
        logger.info("Starting test_connection_establishes")

        with patch(
            "scraper_backend.core.realtime_manager.create_client",
            new=mock_realtime_client,
        ):
            start = asyncio.get_event_loop().time()
            result = await self.manager.connect()
            elapsed = asyncio.get_event_loop().time() - start

            assert result is True
            assert self.manager.is_connected is True
            assert elapsed < 5.0  # Connection timeout

        logger.info("test_connection_establishes passed")

    @pytest.mark.asyncio
    async def test_connection_failure_sets_connected_false(self):
        """Test that connection failure sets is_connected to False."""
        logger.info("Starting test_connection_failure_sets_connected_false")

        with patch(
            "scraper_backend.core.realtime_manager.create_client",
            side_effect=Exception("Connection refused"),
        ):
            result = await self.manager.connect()

            assert result is False
            assert self.manager.is_connected is False

        logger.info("test_connection_failure_sets_connected_false passed")

    @pytest.fixture
    def mock_realtime_client(self):
        """Create a mock AsyncRealtimeClient."""
        with patch(
            "scraper_backend.core.realtime_manager.create_client"
        ) as mock_create:
            client = AsyncMock()
            mock_create.return_value = client
            yield mock_create


class TestRealtimeManagerSubscription:
    """Tests for job subscription and INSERT event handling."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )
        self.callback = MagicMock()

    @pytest.mark.asyncio
    async def test_subscription_receives_insert(self, mock_realtime_client):
        """Job INSERT triggers callback with job data."""
        logger.info("Starting test_subscription_receives_insert")

        # Set up mock client with channel
        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.subscribe = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        # Connect and subscribe
        await self.manager.connect()
        await self.manager.subscribe_to_jobs(self.callback)

        # Simulate INSERT event
        mock_channel.on_postgres_changes.assert_called_once()
        callback = mock_channel.on_postgres_changes.call_args[1]["callback"]

        job_payload = {
            "new": {
                "job_id": "job-123",
                "status": "pending",
                "sku": "TEST-SKU-001",
            }
        }
        await callback(job_payload)

        # Verify callback was invoked
        assert self.callback.called
        called_payload = self.callback.call_args[0][0]
        assert called_payload["job_id"] == "job-123"

        logger.info("test_subscription_receives_insert passed")

    @pytest.mark.asyncio
    async def test_filter_applied_correctly(self, mock_realtime_client):
        """Only pending jobs trigger callback - filter is correctly applied."""
        logger.info("Starting test_filter_applied_correctly")

        # Set up mock client with channel
        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        await self.manager.connect()
        await self.manager.subscribe_to_jobs(self.callback)

        # Verify filter is applied correctly
        mock_channel.on_postgres_changes.assert_called_once_with(
            event="INSERT",
            schema="public",
            table="scrape_jobs",
            filter="status=eq.pending",
            callback=self.manager._handle_job_insert,
        )

        logger.info("test_filter_applied_correctly passed")

    @pytest.mark.asyncio
    async def test_subscription_without_client_raises_error(self):
        """Subscription without client initialization logs error."""
        logger.info("Starting test_subscription_without_client_raises_error")

        await self.manager.subscribe_to_jobs(self.callback)

        # Should log error and return without subscribing
        mock_channel = MagicMock()
        self.manager.client = None

        # Should not raise, just log error
        await self.manager.subscribe_to_jobs(self.callback)

        logger.info("test_subscription_without_client_raises_error passed")


class TestRealtimeManagerDisconnect:
    """Tests for graceful disconnection and cleanup."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(self, mock_realtime_client):
        """Graceful shutdown cleans up WebSocket connection."""
        logger.info("Starting test_disconnect_closes_websocket")

        # Set up mock client
        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.unsubscribe = AsyncMock()
        mock_client.get_channels.return_value = [mock_channel]
        mock_realtime_client.return_value = mock_client

        # Connect and then disconnect
        await self.manager.connect()
        assert self.manager.is_connected is True

        await self.manager.disconnect()

        # Verify cleanup
        mock_channel.unsubscribe.assert_called_once()
        mock_client.close.assert_called_once()
        assert self.manager.is_connected is False

        logger.info("test_disconnect_closes_websocket passed")

    @pytest.mark.asyncio
    async def test_disconnect_with_no_client(self):
        """Disconnect with no client handles gracefully."""
        logger.info("Starting test_disconnect_with_no_client")

        self.manager.client = None
        self.manager._connected = False

        # Should not raise
        await self.manager.disconnect()

        assert self.manager.is_connected is False

        logger.info("test_disconnect_with_no_client passed")


class TestRealtimeManagerReconnection:
    """Tests for automatic reconnection with exponential backoff."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, mock_realtime_client):
        """Automatic reconnection works after disconnection."""
        logger.info("Starting test_reconnect_after_disconnect")

        # Set up mock client
        mock_client = AsyncMock()
        mock_realtime_client.return_value = mock_client

        # First connect succeeds
        await self.manager.connect()
        assert self.manager.is_connected is True

        # Simulate disconnection
        self.manager._connected = False

        # Start reconnection
        self.manager.start_reconnection_loop()
        await asyncio.sleep(0.1)  # Small delay for reconnection to attempt

        # Verify reconnection attempted
        assert self.manager._reconnect_task is not None

        # Clean up
        self.manager._shutdown_event.set()
        await asyncio.sleep(0.1)

        logger.info("test_reconnect_after_disconnect passed")

    @pytest.mark.asyncio
    async def test_shutdown_event_stops_reconnection(self, mock_realtime_client):
        """Shutdown event stops reconnection attempts."""
        logger.info("Starting test_shutdown_event_stops_reconnection")

        # Set up mock client to fail connection
        mock_realtime_client.side_effect = Exception("Connection refused")

        await self.manager.connect()
        self.manager._connected = False

        # Start reconnection
        self.manager.start_reconnection_loop()

        # Set shutdown event
        await asyncio.sleep(0.1)  # Let it start
        self.manager._shutdown_event.set()

        # Give time for reconnection loop to check shutdown
        await asyncio.sleep(0.1)

        # Verify shutdown event stopped reconnection
        assert self.manager._shutdown_event.is_set()

        # Clean up task
        if self.manager._reconnect_task and not self.manager._reconnect_task.done():
            self.manager._reconnect_task.cancel()
            try:
                await self.manager._reconnect_task
            except asyncio.CancelledError:
                pass

        logger.info("test_shutdown_event_stops_reconnection passed")

    @pytest.fixture
    def mock_realtime_client(self):
        """Create a mock AsyncRealtimeClient."""
        with patch(
            "scraper_backend.core.realtime_manager.create_client"
        ) as mock_create:
            client = AsyncMock()
            mock_create.return_value = client
            yield mock_create


class TestRealtimeManagerCallback:
    """Tests for job callback invocation."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )
        self.callback = AsyncMock()

    @pytest.mark.asyncio
    async def test_job_callback_invoked(self, mock_realtime_client):
        """Callback is called when job is received."""
        logger.info("Starting test_job_callback_invoked")

        # Set up mock client
        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        await self.manager.connect()
        await self.manager.subscribe_to_jobs(self.callback)

        # Simulate INSERT event
        callback = mock_channel.on_postgres_changes.call_args[1]["callback"]
        job_payload = {"new": {"job_id": "job-456", "status": "pending"}}
        await callback(job_payload)

        # Verify callback was invoked
        self.callback.assert_called_once_with(job_payload["new"])

        logger.info("test_job_callback_invoked passed")

    @pytest.mark.asyncio
    async def test_sync_callback_handled(self, mock_realtime_client):
        """Sync callback is handled correctly."""
        logger.info("Starting test_sync_callback_handled")

        sync_callback = MagicMock()
        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        await self.manager.connect()
        await self.manager.subscribe_to_jobs(sync_callback)

        # Simulate INSERT event
        callback = mock_channel.on_postgres_changes.call_args[1]["callback"]
        job_payload = {"new": {"job_id": "job-789", "status": "pending"}}
        await callback(job_payload)

        # Verify sync callback was invoked (not awaited)
        sync_callback.assert_called_once()

        logger.info("test_sync_callback_handled passed")

    @pytest.fixture
    def mock_realtime_client(self):
        """Create a mock AsyncRealtimeClient."""
        with patch(
            "scraper_backend.core.realtime_manager.create_client"
        ) as mock_create:
            client = AsyncMock()
            mock_create.return_value = client
            yield mock_create


class TestRealtimeManagerQueue:
    """Tests for job queue operations."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )

    @pytest.mark.asyncio
    async def test_queue_operations(self):
        """Job queuing works correctly."""
        logger.info("Starting test_queue_operations")

        # Initial state
        assert self.manager.queue_size() == 0

        # Add jobs to queue
        job1 = {"job_id": "job-001", "sku": "SKU001"}
        job2 = {"job_id": "job-002", "sku": "SKU002"}

        await self.manager._pending_jobs.put(job1)
        await self.manager._pending_jobs.put(job2)

        assert self.manager.queue_size() == 2

        # Get jobs
        retrieved_job1 = await self.manager.get_pending_job()
        assert retrieved_job1 == job1

        retrieved_job2 = await self.manager.get_pending_job()
        assert retrieved_job2 == job2

        # Queue should be empty
        assert self.manager.queue_size() == 0

        logger.info("test_queue_operations passed")

    @pytest.mark.asyncio
    async def test_clear_pending_jobs(self):
        """Clear all pending jobs from queue."""
        logger.info("Starting test_clear_pending_jobs")

        # Add jobs to queue
        for i in range(3):
            await self.manager._pending_jobs.put({"job_id": f"job-{i}"})

        assert self.manager.queue_size() == 3

        # Clear jobs
        self.manager.clear_pending_jobs()

        assert self.manager.queue_size() == 0

        logger.info("test_clear_pending_jobs passed")

    @pytest.mark.asyncio
    async def test_get_pending_job_timeout(self):
        """get_pending_job returns None on timeout."""
        logger.info("Starting test_get_pending_job_timeout")

        result = await self.manager.get_pending_job()

        assert result is None

        logger.info("test_get_pending_job_timeout passed")

    @pytest.mark.asyncio
    async def test_wait_for_job(self):
        """wait_for_job retrieves job from queue."""
        logger.info("Starting test_wait_for_job")

        # Add a job
        test_job = {"job_id": "wait-test-job"}
        await self.manager._pending_jobs.put(test_job)

        # Wait for job
        result = await self.manager.wait_for_job(timeout=1.0)

        assert result == test_job

        logger.info("test_wait_for_job passed")


class TestRealtimeManagerProperties:
    """Tests for RealtimeManager properties."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )

    def test_is_connected_initial_state(self):
        """is_connected returns False initially."""
        assert self.manager.is_connected is False

    def test_reconnect_delays_configured(self):
        """Reconnect delays are properly configured."""
        assert len(self.manager.RECONNECT_DELAYS) == 6
        assert self.manager.RECONNECT_DELAYS == [1, 2, 4, 8, 16, 32]

    def test_max_reconnect_attempts_configured(self):
        """Max reconnect attempts is properly configured."""
        assert self.manager.MAX_RECONNECT_ATTEMPTS == 10

    def test_manager_attributes(self):
        """Manager has expected attributes set."""
        assert self.manager.supabase_url == "https://test.supabase.co"
        assert self.manager.service_key == "test-service-key"
        assert self.manager.runner_name == "test-runner"
        assert self.manager.client is None
        assert self.manager._connected is False
        assert self.manager._reconnect_task is None
        assert not self.manager._shutdown_event.is_set()


class TestRealtimeManagerJobInsertion:
    """Tests for job INSERT event handling edge cases."""

    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = RealtimeManager(
            supabase_url="https://test.supabase.co",
            service_key="test-service-key",
            runner_name="test-runner",
        )
        self.callback = AsyncMock()

    @pytest.mark.asyncio
    async def test_insert_with_no_new_data(self, mock_realtime_client):
        """INSERT with no 'new' data logs warning and returns."""
        logger.info("Starting test_insert_with_no_new_data")

        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        await self.manager.connect()
        await self.manager.subscribe_to_jobs(self.callback)

        # Get the callback
        callback = mock_channel.on_postgres_changes.call_args[1]["callback"]

        # Call with no 'new' data
        await callback({})
        await callback({"new": None})

        # Callback should not have been called
        self.callback.assert_not_called()

        logger.info("test_insert_with_no_new_data passed")

    @pytest.mark.asyncio
    async def test_multiple_job_inserts(self, mock_realtime_client):
        """Multiple job INSERTs are all queued correctly."""
        logger.info("Starting test_multiple_job_inserts")

        mock_client = AsyncMock()
        mock_channel = AsyncMock()
        mock_client.channel.return_value = mock_channel
        mock_realtime_client.return_value = mock_client

        await self.manager.connect()
        await self.manager.subscribe_to_jobs(self.callback)

        # Get the callback
        callback = mock_channel.on_postgres_changes.call_args[1]["callback"]

        # Insert multiple jobs
        for i in range(5):
            await callback({"new": {"job_id": f"job-{i}", "sku": f"SKU-{i}"}})

        assert self.manager.queue_size() == 5

        # Verify all jobs retrieved
        for i in range(5):
            job = await self.manager.get_pending_job()
            assert job["job_id"] == f"job-{i}"

        logger.info("test_multiple_job_inserts passed")

    @pytest.fixture
    def mock_realtime_client(self):
        """Create a mock AsyncRealtimeClient."""
        with patch(
            "scraper_backend.core.realtime_manager.create_client"
        ) as mock_create:
            client = AsyncMock()
            mock_create.return_value = client
            yield mock_create
