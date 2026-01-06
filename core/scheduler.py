"""
Scheduler and Worker Orchestration for ProductScraper.

This module provides asyncio-based scheduling with per-site concurrency control:
- Login sites (requires_login=True) are limited to 1 concurrent worker
- Non-login sites can have up to site_max_workers concurrent workers
- Global max_workers caps total concurrent workers across all sites
- Per-site FIFO queues ensure ordering and prevent cross-site blocking

Architecture:
    WorkerOrchestrator
    ├── Global Semaphore(max_workers)  # Hard ceiling on total concurrency
    ├── SiteScheduler("amazon")        # Non-login: Semaphore(site_max_workers)
    ├── SiteScheduler("petfoodex")     # Login: Semaphore(1)
    └── SiteScheduler("walmart")       # Non-login: Semaphore(site_max_workers)

Design Rationale:
    - asyncio chosen over ThreadPoolExecutor because:
      1. Web scraping is I/O-bound (network waits)
      2. Better cancellation semantics with Task.cancel()
      3. Per-site semaphores/queues map naturally to asyncio primitives
      4. Native integration with async Playwright

    - Two-level concurrency control:
      1. Global Semaphore: Hard cap on total concurrent workers
      2. Per-Site Semaphore: Site-specific limits (1 for login sites)
      Both must be acquired before a task can start.

Alternatives Considered:
    - ThreadPoolExecutor: Simpler but no per-site isolation, harder cancellation
    - Multiprocessing: True parallelism but IPC overhead, memory duplication

Usage:
    from core.scheduler import WorkerOrchestrator, SiteConfig

    config = {
        "amazon": SiteConfig(requires_login=False, site_max_workers=3),
        "petfoodex": SiteConfig(requires_login=True),  # Auto limited to 1
    }

    orchestrator = WorkerOrchestrator(max_workers=5, site_configs=config)
    orchestrator.enqueue("amazon", "SKU123")
    orchestrator.enqueue("petfoodex", "SKU456")

    async def my_scraper(site: str, sku: str) -> dict:
        # Your scraping logic here
        pass

    results = await orchestrator.run(my_scraper)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)


# Type alias for scraper function
T = TypeVar("T")
ScraperFunc = Callable[[str, str], Awaitable[dict[str, Any]]]


class TaskStatus(Enum):
    """Status of a scheduled task."""

    QUEUED = "queued"
    WAITING = "waiting"  # Waiting for semaphore
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SchedulerEventType(Enum):
    """Types of scheduler events for logging/observability."""

    TASK_QUEUED = "task_queued"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    SITE_QUEUE_EMPTY = "site_queue_empty"
    SCHEDULER_STARTED = "scheduler_started"
    SCHEDULER_STOPPED = "scheduler_stopped"
    SHUTDOWN_INITIATED = "shutdown_initiated"


@dataclass
class SchedulerEvent:
    """Event emitted by the scheduler for logging/observability."""

    event_type: SchedulerEventType
    timestamp: float = field(default_factory=time.time)
    task_id: str | None = None
    site: str | None = None
    sku: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"[{self.event_type.value}]"]
        if self.site:
            parts.append(f"site={self.site}")
        if self.sku:
            parts.append(f"sku={self.sku}")
        if self.task_id:
            parts.append(f"task_id={self.task_id[:8]}")
        if self.message:
            parts.append(self.message)
        return " ".join(parts)


@dataclass
class SiteConfig:
    """Configuration for a single site's concurrency limits.

    Attributes:
        requires_login: If True, site is limited to 1 concurrent worker
        site_max_workers: Max concurrent workers for this site (ignored if requires_login)
    """

    requires_login: bool = False
    site_max_workers: int = 2

    @property
    def effective_max_workers(self) -> int:
        """Get effective max workers (1 if login required, else site_max_workers)."""
        return 1 if self.requires_login else self.site_max_workers


@dataclass
class ScheduledTask:
    """A task scheduled for execution."""

    task_id: str
    site: str
    sku: str
    status: TaskStatus = TaskStatus.QUEUED
    result: dict[str, Any] | None = None
    error: Exception | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    @property
    def duration_ms(self) -> float | None:
        """Get task duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return None

    @property
    def queue_time_ms(self) -> float | None:
        """Get time spent waiting in queue in milliseconds."""
        if self.started_at:
            return (self.started_at - self.created_at) * 1000
        return None


@dataclass
class SchedulerStats:
    """Statistics for the scheduler."""

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    queued_tasks: int = 0
    active_tasks: int = 0
    peak_concurrent: int = 0
    total_duration_ms: float = 0.0
    sites_stats: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "queued_tasks": self.queued_tasks,
            "active_tasks": self.active_tasks,
            "peak_concurrent": self.peak_concurrent,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success_rate": self.completed_tasks / self.total_tasks
            if self.total_tasks > 0
            else 0.0,
            "sites": self.sites_stats,
        }


# Type alias for event handler
EventHandler = Callable[[SchedulerEvent], None]


class SiteScheduler:
    """Scheduler for a single site with its own queue and concurrency limit.

    Each site maintains:
    - A FIFO queue of SKUs to process
    - A semaphore limiting concurrent workers for this site
    - Statistics tracking
    """

    def __init__(
        self,
        site_name: str,
        config: SiteConfig,
        global_semaphore: asyncio.Semaphore,
        event_handler: EventHandler | None = None,
    ):
        """Initialize site scheduler.

        Args:
            site_name: Name of the site (e.g., "amazon", "petfoodex")
            config: Site configuration with concurrency settings
            global_semaphore: Global semaphore for overall concurrency limit
            event_handler: Optional callback for scheduler events
        """
        self.site_name = site_name
        self.config = config
        self._global_semaphore = global_semaphore
        self._event_handler = event_handler

        # Per-site semaphore for concurrency control
        self._site_semaphore = asyncio.Semaphore(config.effective_max_workers)

        # FIFO queue for SKUs
        self._queue: asyncio.Queue[ScheduledTask] = asyncio.Queue()

        # Track active tasks
        self._active_tasks: dict[str, asyncio.Task[ScheduledTask]] = {}
        self._completed_tasks: list[ScheduledTask] = []

        # Statistics
        self._queued_count = 0
        self._active_count = 0
        self._completed_count = 0
        self._failed_count = 0
        self._cancelled_count = 0

        # Control flags
        self._running = False
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"SiteScheduler initialized: {site_name}, "
            f"max_workers={config.effective_max_workers}, "
            f"requires_login={config.requires_login}"
        )

    def enqueue(self, sku: str) -> ScheduledTask:
        """Add a SKU to the queue for processing.

        Args:
            sku: SKU to process

        Returns:
            ScheduledTask object for tracking
        """
        task = ScheduledTask(
            task_id=str(uuid.uuid4()),
            site=self.site_name,
            sku=sku,
        )
        self._queue.put_nowait(task)
        self._queued_count += 1

        self._emit_event(
            SchedulerEvent(
                event_type=SchedulerEventType.TASK_QUEUED,
                task_id=task.task_id,
                site=self.site_name,
                sku=sku,
                metadata={"queue_size": self._queue.qsize()},
            )
        )

        return task

    async def run(
        self,
        scraper_func: ScraperFunc,
    ) -> list[ScheduledTask]:
        """Process all queued tasks for this site.

        Args:
            scraper_func: Async function to execute for each SKU

        Returns:
            List of completed ScheduledTask objects
        """
        self._running = True
        self._shutdown_event.clear()
        workers: list[asyncio.Task[None]] = []

        try:
            # Start workers equal to max concurrent for this site
            num_workers = self.config.effective_max_workers
            for i in range(num_workers):
                worker = asyncio.create_task(
                    self._worker(scraper_func, worker_id=i), name=f"{self.site_name}_worker_{i}"
                )
                workers.append(worker)

            # Wait for queue to be fully processed
            await self._queue.join()

        except asyncio.CancelledError:
            logger.info(f"SiteScheduler {self.site_name} cancelled")
            raise
        finally:
            self._running = False
            # Cancel all workers
            for worker in workers:
                worker.cancel()
            # Wait for workers to finish
            await asyncio.gather(*workers, return_exceptions=True)

        return self._completed_tasks.copy()

    async def _worker(
        self,
        scraper_func: ScraperFunc,
        worker_id: int,
    ) -> None:
        """Worker coroutine that processes tasks from the queue."""
        while not self._shutdown_event.is_set():
            try:
                # Get task from queue with timeout for shutdown check
                try:
                    task = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=0.5,
                    )
                except TimeoutError:
                    continue

                # Process the task
                try:
                    await self._process_task(task, scraper_func, worker_id)
                finally:
                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {self.site_name}_{worker_id} error: {e}")

    async def _process_task(
        self,
        task: ScheduledTask,
        scraper_func: ScraperFunc,
        worker_id: int,
    ) -> None:
        """Process a single task with proper semaphore handling."""
        task.status = TaskStatus.WAITING

        # Acquire both semaphores (global first, then site-specific)
        # This ensures we respect both limits
        async with self._global_semaphore:
            async with self._site_semaphore:
                self._active_count += 1
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()

                self._emit_event(
                    SchedulerEvent(
                        event_type=SchedulerEventType.TASK_STARTED,
                        task_id=task.task_id,
                        site=self.site_name,
                        sku=task.sku,
                        metadata={
                            "worker_id": worker_id,
                            "queue_time_ms": task.queue_time_ms,
                        },
                    )
                )

                try:
                    result = await scraper_func(self.site_name, task.sku)
                    task.result = result
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = time.time()
                    self._completed_count += 1

                    self._emit_event(
                        SchedulerEvent(
                            event_type=SchedulerEventType.TASK_COMPLETED,
                            task_id=task.task_id,
                            site=self.site_name,
                            sku=task.sku,
                            metadata={
                                "duration_ms": task.duration_ms,
                                "worker_id": worker_id,
                            },
                        )
                    )

                except asyncio.CancelledError:
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = time.time()
                    self._cancelled_count += 1

                    self._emit_event(
                        SchedulerEvent(
                            event_type=SchedulerEventType.TASK_CANCELLED,
                            task_id=task.task_id,
                            site=self.site_name,
                            sku=task.sku,
                        )
                    )
                    raise

                except Exception as e:
                    task.error = e
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    self._failed_count += 1

                    self._emit_event(
                        SchedulerEvent(
                            event_type=SchedulerEventType.TASK_FAILED,
                            task_id=task.task_id,
                            site=self.site_name,
                            sku=task.sku,
                            message=str(e),
                        )
                    )

                finally:
                    self._active_count -= 1
                    self._completed_tasks.append(task)

    def shutdown(self) -> None:
        """Signal shutdown to stop processing new tasks."""
        self._shutdown_event.set()
        self._running = False

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics for this site."""
        return {
            "site": self.site_name,
            "requires_login": self.config.requires_login,
            "max_workers": self.config.effective_max_workers,
            "queued": self._queue.qsize(),
            "active": self._active_count,
            "completed": self._completed_count,
            "failed": self._failed_count,
            "cancelled": self._cancelled_count,
            "total_submitted": self._queued_count,
        }

    def _emit_event(self, event: SchedulerEvent) -> None:
        """Emit a scheduler event."""
        logger.debug(str(event))
        if self._event_handler:
            try:
                self._event_handler(event)
            except Exception as e:
                logger.warning(f"Event handler error: {e}")


class WorkerOrchestrator:
    """Orchestrates multiple SiteSchedulers with global concurrency control.

    This is the main entry point for scheduling scraping tasks across multiple sites.
    It ensures:
    - Global max_workers limit is respected across all sites
    - Per-site limits are enforced (1 for login sites, configurable for others)
    - Tasks for one site don't block unrelated sites
    - Graceful shutdown with in-flight task completion

    Example:
        orchestrator = WorkerOrchestrator(max_workers=5)
        orchestrator.register_site("amazon", SiteConfig(requires_login=False, site_max_workers=3))
        orchestrator.register_site("petfoodex", SiteConfig(requires_login=True))

        orchestrator.enqueue("amazon", "SKU1")
        orchestrator.enqueue("amazon", "SKU2")
        orchestrator.enqueue("petfoodex", "SKU3")

        results = await orchestrator.run(my_scraper_func)
    """

    def __init__(
        self,
        max_workers: int = 5,
        site_configs: dict[str, SiteConfig] | None = None,
        event_handler: EventHandler | None = None,
    ):
        """Initialize the orchestrator.

        Args:
            max_workers: Global maximum concurrent workers across all sites
            site_configs: Optional dict of site_name -> SiteConfig
            event_handler: Optional callback for scheduler events
        """
        self.max_workers = max_workers
        self._event_handler = event_handler

        # Global semaphore for overall concurrency limit
        self._global_semaphore = asyncio.Semaphore(max_workers)

        # Site schedulers
        self._site_schedulers: dict[str, SiteScheduler] = {}

        # Register initial site configs
        if site_configs:
            for site_name, config in site_configs.items():
                self.register_site(site_name, config)

        # Track global state
        self._running = False
        self._shutdown_requested = False
        self._active_count = 0
        self._peak_concurrent = 0
        self._start_time: float | None = None

        # All completed tasks
        self._all_results: list[ScheduledTask] = []

        logger.info(f"WorkerOrchestrator initialized with max_workers={max_workers}")

    def register_site(
        self,
        site_name: str,
        config: SiteConfig | None = None,
    ) -> SiteScheduler:
        """Register a site with its concurrency configuration.

        Args:
            site_name: Unique site identifier
            config: Site configuration (defaults to non-login, 2 workers)

        Returns:
            SiteScheduler instance for the site
        """
        if site_name in self._site_schedulers:
            logger.warning(f"Site {site_name} already registered, updating config")

        config = config or SiteConfig()

        # Ensure site_max_workers doesn't exceed global max
        if config.effective_max_workers > self.max_workers:
            logger.warning(
                f"Site {site_name} max_workers ({config.effective_max_workers}) "
                f"exceeds global max ({self.max_workers}), will be capped"
            )

        scheduler = SiteScheduler(
            site_name=site_name,
            config=config,
            global_semaphore=self._global_semaphore,
            event_handler=self._event_handler,
        )
        self._site_schedulers[site_name] = scheduler

        return scheduler

    def enqueue(self, site_name: str, sku: str) -> ScheduledTask:
        """Add a task to a site's queue.

        Args:
            site_name: Site to process the SKU
            sku: SKU to process

        Returns:
            ScheduledTask for tracking

        Raises:
            ValueError: If site is not registered
        """
        if site_name not in self._site_schedulers:
            raise ValueError(
                f"Site '{site_name}' not registered. "
                f"Call register_site() first or pass site_configs to __init__"
            )

        return self._site_schedulers[site_name].enqueue(sku)

    def enqueue_batch(
        self,
        tasks: list[tuple[str, str]],
    ) -> list[ScheduledTask]:
        """Enqueue multiple tasks at once.

        Args:
            tasks: List of (site_name, sku) tuples

        Returns:
            List of ScheduledTask objects
        """
        return [self.enqueue(site, sku) for site, sku in tasks]

    async def run(
        self,
        scraper_func: ScraperFunc,
    ) -> list[ScheduledTask]:
        """Run all scheduled tasks across all sites.

        Args:
            scraper_func: Async function(site, sku) -> dict to execute for each task

        Returns:
            List of all completed ScheduledTask objects
        """
        if self._running:
            raise RuntimeError("Orchestrator is already running")

        self._running = True
        self._shutdown_requested = False
        self._start_time = time.time()
        self._all_results = []

        self._emit_event(
            SchedulerEvent(
                event_type=SchedulerEventType.SCHEDULER_STARTED,
                metadata={
                    "max_workers": self.max_workers,
                    "sites": list(self._site_schedulers.keys()),
                },
            )
        )

        try:
            # Run all site schedulers concurrently
            site_tasks = [
                asyncio.create_task(scheduler.run(scraper_func), name=f"site_{site_name}")
                for site_name, scheduler in self._site_schedulers.items()
            ]

            # Wait for all sites to complete
            results = await asyncio.gather(*site_tasks, return_exceptions=True)

            # Collect results
            for result in results:
                if isinstance(result, list):
                    self._all_results.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Site scheduler error: {result}")

        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled, initiating graceful shutdown")
            await self.shutdown()
            raise
        finally:
            self._running = False
            self._emit_event(
                SchedulerEvent(
                    event_type=SchedulerEventType.SCHEDULER_STOPPED,
                    metadata=self.get_stats().to_dict(),
                )
            )

        return self._all_results

    async def shutdown(self, timeout: float = 30.0) -> None:
        """Gracefully shutdown the orchestrator.

        Args:
            timeout: Maximum time to wait for in-flight tasks
        """
        if self._shutdown_requested:
            return

        self._shutdown_requested = True

        self._emit_event(
            SchedulerEvent(
                event_type=SchedulerEventType.SHUTDOWN_INITIATED,
                message=f"Shutdown requested, timeout={timeout}s",
            )
        )

        # Signal all site schedulers to shutdown
        for scheduler in self._site_schedulers.values():
            scheduler.shutdown()

        # Wait for completion with timeout
        # In-flight tasks will complete, but no new tasks will start
        logger.info(f"Waiting up to {timeout}s for in-flight tasks to complete...")

    def get_stats(self) -> SchedulerStats:
        """Get current scheduler statistics."""
        stats = SchedulerStats()

        for site_name, scheduler in self._site_schedulers.items():
            site_stats = scheduler.get_stats()
            stats.total_tasks += site_stats["total_submitted"]
            stats.completed_tasks += site_stats["completed"]
            stats.failed_tasks += site_stats["failed"]
            stats.cancelled_tasks += site_stats["cancelled"]
            stats.queued_tasks += site_stats["queued"]
            stats.active_tasks += site_stats["active"]
            stats.sites_stats[site_name] = site_stats

        if self._start_time:
            stats.total_duration_ms = (time.time() - self._start_time) * 1000

        return stats

    def get_site_scheduler(self, site_name: str) -> SiteScheduler | None:
        """Get a specific site scheduler."""
        return self._site_schedulers.get(site_name)

    def _emit_event(self, event: SchedulerEvent) -> None:
        """Emit a scheduler event."""
        logger.info(str(event))
        if self._event_handler:
            try:
                self._event_handler(event)
            except Exception as e:
                logger.warning(f"Event handler error: {e}")


def load_site_configs_from_settings(
    settings_dict: dict[str, Any],
    scraper_configs: dict[str, Any] | None = None,
) -> dict[str, SiteConfig]:
    """Load site configurations from settings.json format.

    Expected settings format:
    {
        "max_workers": 5,
        "site_configs": {
            "amazon": {"site_max_workers": 3, "requires_login": false},
            "petfoodex": {"site_max_workers": 2, "requires_login": true},
        }
    }

    If site_configs is not present, will auto-detect from scraper_configs
    (YAML configs with 'login' section are considered login sites).

    Args:
        settings_dict: Settings dictionary (from settings.json)
        scraper_configs: Optional dict of scraper configs (from YAML files)

    Returns:
        Dict of site_name -> SiteConfig
    """
    global_max = settings_dict.get("max_workers", 5)
    site_configs_raw = settings_dict.get("site_configs", {})
    default_site_max = settings_dict.get("default_site_max_workers", 2)

    result: dict[str, SiteConfig] = {}

    # Process explicit site configs
    for site_name, config in site_configs_raw.items():
        if isinstance(config, dict):
            requires_login = config.get("requires_login", False)
            site_max = config.get("site_max_workers", default_site_max)
            # Cap site_max at global max
            site_max = min(site_max, global_max)
            result[site_name] = SiteConfig(
                requires_login=requires_login,
                site_max_workers=site_max,
            )

    # Auto-detect from scraper configs if available
    if scraper_configs:
        for site_name, config in scraper_configs.items():
            if site_name not in result:
                # Detect login requirement from scraper config
                has_login = False
                if hasattr(config, "requires_login"):
                    has_login = config.requires_login()
                elif isinstance(config, dict):
                    has_login = config.get("login") is not None

                result[site_name] = SiteConfig(
                    requires_login=has_login,
                    site_max_workers=min(default_site_max, global_max),
                )

    return result


async def create_orchestrator_from_settings(
    settings_dict: dict[str, Any],
    scraper_configs: dict[str, Any] | None = None,
    event_handler: EventHandler | None = None,
) -> WorkerOrchestrator:
    """Factory function to create an orchestrator from settings.json.

    Args:
        settings_dict: Settings dictionary
        scraper_configs: Optional scraper configurations
        event_handler: Optional event callback

    Returns:
        Configured WorkerOrchestrator
    """
    max_workers = settings_dict.get("max_workers", 5)
    site_configs = load_site_configs_from_settings(settings_dict, scraper_configs)

    return WorkerOrchestrator(
        max_workers=max_workers,
        site_configs=site_configs,
        event_handler=event_handler,
    )
