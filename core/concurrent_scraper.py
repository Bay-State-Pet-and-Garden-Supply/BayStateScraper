"""
Concurrent scraping manager for parallel execution of scrapers.

Provides browser pooling, task distribution, and resource throttling
to achieve 3+ simultaneous scraper operations.
"""
from __future__ import annotations


import logging
import queue
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.database.supabase_sync import supabase_sync
from core.memory_manager import MemoryManager, get_memory_manager
from core.performance_profiler import OperationType, PerformanceProfiler

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a scraping task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceType(Enum):
    """Types of resources that can be throttled."""

    BROWSER = "browser"
    NETWORK = "network"
    CPU = "cpu"
    MEMORY = "memory"


@dataclass
class ScrapingTask:
    """Represents a single scraping task."""

    task_id: str
    scraper_name: str
    sku: str
    priority: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: Exception | None = None
    start_time: float | None = None
    end_time: float | None = None
    retries: int = 0
    max_retries: int = 3

    @property
    def duration_ms(self) -> float | None:
        """Get task duration in milliseconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None


@dataclass
class WorkerStats:
    """Statistics for a worker thread."""

    worker_id: int
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_time_ms: float = 0.0
    current_task: str | None = None
    is_idle: bool = True

    @property
    def avg_task_time_ms(self) -> float:
        """Average task completion time."""
        if self.tasks_completed > 0:
            return self.total_time_ms / self.tasks_completed
        return 0.0


@dataclass
class ConcurrencyStats:
    """Overall concurrency statistics."""

    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    active_workers: int
    peak_concurrent: int
    total_duration_ms: float
    tasks_per_second: float
    worker_stats: list[WorkerStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "pending_tasks": self.pending_tasks,
            "success_rate": self.completed_tasks / self.total_tasks if self.total_tasks > 0 else 0,
            "active_workers": self.active_workers,
            "peak_concurrent": self.peak_concurrent,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "tasks_per_second": round(self.tasks_per_second, 4),
            "worker_stats": [
                {
                    "worker_id": w.worker_id,
                    "tasks_completed": w.tasks_completed,
                    "tasks_failed": w.tasks_failed,
                    "avg_task_time_ms": round(w.avg_task_time_ms, 2),
                }
                for w in self.worker_stats
            ],
        }


class ResourceThrottler:
    """
    Throttles resource usage to prevent overload.

    Implements token bucket algorithm for rate limiting.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        requests_per_second: float = 1.0,
        memory_limit_mb: float = 500.0,
    ):
        """
        Initialize the resource throttler.

        Args:
            max_concurrent: Maximum concurrent operations
            requests_per_second: Rate limit for requests
            memory_limit_mb: Memory limit before throttling (default 500MB for large scrapes)
        """
        self.max_concurrent = max_concurrent
        self.requests_per_second = requests_per_second
        self.memory_limit_mb = memory_limit_mb

        self._semaphore = threading.Semaphore(max_concurrent)
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._tokens = requests_per_second
        self._token_refresh_time = time.time()

        self._memory_manager = get_memory_manager()

    @contextmanager
    def acquire(self, timeout: float | None = None) -> Iterator[bool]:
        """
        Acquire resources for an operation.

        Args:
            timeout: Maximum time to wait for resources

        Yields:
            True if acquired, False if timed out
        """
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            yield False
            return

        try:
            # Wait for rate limit
            self._wait_for_rate_limit()

            # Check memory
            while not self._check_memory():
                logger.warning("Memory limit reached, waiting...")
                time.sleep(1.0)
                self._memory_manager.trigger_gc()

            yield True
        finally:
            self._semaphore.release()

    def _wait_for_rate_limit(self) -> None:
        """Wait for rate limit token."""
        with self._lock:
            now = time.time()

            # Refresh tokens based on elapsed time
            elapsed = now - self._token_refresh_time
            self._tokens = min(
                self.requests_per_second,
                self._tokens + elapsed * self.requests_per_second,
            )
            self._token_refresh_time = now

            # Wait if no tokens available
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.requests_per_second
                time.sleep(wait_time)
                self._tokens = 1

            self._tokens -= 1

    def _check_memory(self) -> bool:
        """Check if memory is within limits."""
        current_mb = self._memory_manager.get_current_usage_mb()
        return current_mb < self.memory_limit_mb

    def get_stats(self) -> dict[str, Any]:
        """Get throttler statistics."""
        return {
            "max_concurrent": self.max_concurrent,
            "requests_per_second": self.requests_per_second,
            "memory_limit_mb": self.memory_limit_mb,
            "current_memory_mb": self._memory_manager.get_current_usage_mb(),
            "available_slots": self._semaphore._value,
        }


class BrowserPool:
    """
    Pool of browser instances for reuse.

    Manages browser lifecycle and provides efficient browser allocation.
    """

    def __init__(
        self,
        pool_size: int = 3,
        browser_factory: Callable[[], Any] | None = None,
        browser_reset: Callable[[Any], None] | None = None,
        max_uses_per_browser: int = 50,
    ):
        """
        Initialize the browser pool.

        Args:
            pool_size: Number of browsers to maintain
            browser_factory: Function to create new browsers
            browser_reset: Function to reset browser state
            max_uses_per_browser: Maximum uses before recycling
        """
        self.pool_size = pool_size
        self._browser_factory = browser_factory
        self._browser_reset = browser_reset
        self.max_uses_per_browser = max_uses_per_browser

        self._pool: queue.Queue[tuple[Any, int]] = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created = 0
        self._recycled = 0
        self._active = 0

    def initialize(self) -> None:
        """Pre-create browsers in the pool."""
        if not self._browser_factory:
            logger.warning("No browser factory provided, pool will create on demand")
            return

        logger.info(f"Initializing browser pool with {self.pool_size} browsers...")
        for i in range(self.pool_size):
            try:
                browser = self._browser_factory()
                self._pool.put((browser, 0))
                with self._lock:
                    self._created += 1
                logger.debug(f"Created browser {i + 1}/{self.pool_size}")
            except Exception as e:
                logger.error(f"Failed to create browser {i + 1}: {e}")

        logger.info(f"Browser pool initialized with {self._pool.qsize()} browsers")

    @contextmanager
    def get_browser(self, timeout: float = 30.0) -> Iterator[Any]:
        """
        Get a browser from the pool.

        Args:
            timeout: Maximum time to wait for a browser

        Yields:
            Browser instance

        Raises:
            TimeoutError: If no browser available within timeout
        """
        browser = None
        use_count = 0

        try:
            # Try to get from pool
            browser, use_count = self._pool.get(timeout=timeout)
            with self._lock:
                self._active += 1

            # Reset browser state if needed
            if self._browser_reset:
                try:
                    self._browser_reset(browser)
                except Exception as e:
                    logger.warning(f"Browser reset failed: {e}")

            yield browser

        except queue.Empty:
            # Pool empty, create new if possible
            if self._browser_factory and self._active < self.pool_size:
                logger.info("Pool empty, creating new browser")
                browser = self._browser_factory()
                with self._lock:
                    self._created += 1
                    self._active += 1
                yield browser
            else:
                raise TimeoutError("No browser available in pool")

        finally:
            if browser is not None:
                use_count += 1

                # Check if browser needs recycling
                if use_count >= self.max_uses_per_browser:
                    logger.debug(f"Recycling browser after {use_count} uses")
                    self._recycle_browser(browser)
                else:
                    # Return to pool
                    try:
                        self._pool.put_nowait((browser, use_count))
                    except queue.Full:
                        logger.warning("Pool full, closing browser")
                        self._close_browser(browser)

                with self._lock:
                    self._active -= 1

    def _recycle_browser(self, browser: Any) -> None:
        """Recycle a browser by closing and creating new."""
        self._close_browser(browser)

        if self._browser_factory:
            try:
                new_browser = self._browser_factory()
                self._pool.put_nowait((new_browser, 0))
                with self._lock:
                    self._recycled += 1
                    self._created += 1
            except Exception as e:
                logger.error(f"Failed to recycle browser: {e}")

    def _close_browser(self, browser: Any) -> None:
        """Safely close a browser."""
        try:
            if hasattr(browser, "quit"):
                browser.quit()
            elif hasattr(browser, "close"):
                browser.close()
        except Exception as e:
            logger.debug(f"Error closing browser: {e}")

    def shutdown(self) -> None:
        """Close all browsers and shutdown pool."""
        logger.info("Shutting down browser pool...")

        while not self._pool.empty():
            try:
                browser, _ = self._pool.get_nowait()
                self._close_browser(browser)
            except queue.Empty:
                break

        logger.info("Browser pool shutdown complete")

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        return {
            "pool_size": self.pool_size,
            "available": self._pool.qsize(),
            "active": self._active,
            "created": self._created,
            "recycled": self._recycled,
            "max_uses_per_browser": self.max_uses_per_browser,
        }


class TaskQueue:
    """
    Priority queue for scraping tasks.

    Supports priority ordering and fair distribution across scrapers.
    """

    def __init__(self, max_size: int = 10000):
        """
        Initialize the task queue.

        Args:
            max_size: Maximum queue size
        """
        self.max_size = max_size
        self._queue: queue.PriorityQueue[tuple[int, float, ScrapingTask]] = queue.PriorityQueue(
            maxsize=max_size
        )
        self._lock = threading.Lock()
        self._task_count = 0
        self._completed_count = 0
        self._failed_count = 0

    def put(self, task: ScrapingTask, block: bool = True, timeout: float | None = None) -> None:
        """
        Add a task to the queue.

        Args:
            task: Task to add
            block: Whether to block if queue is full
            timeout: Timeout for blocking
        """
        # Priority tuple: (priority, timestamp, task)
        # Lower priority number = higher priority
        # Timestamp ensures FIFO within same priority
        priority_tuple = (-task.priority, time.time(), task)
        self._queue.put(priority_tuple, block=block, timeout=timeout)

        with self._lock:
            self._task_count += 1

    def get(self, block: bool = True, timeout: float | None = None) -> ScrapingTask:
        """
        Get next task from queue.

        Args:
            block: Whether to block if queue is empty
            timeout: Timeout for blocking

        Returns:
            Next task
        """
        _, _, task = self._queue.get(block=block, timeout=timeout)
        return task

    def mark_completed(self, success: bool = True) -> None:
        """Mark a task as completed."""
        with self._lock:
            if success:
                self._completed_count += 1
            else:
                self._failed_count += 1

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    def qsize(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            return {
                "total_submitted": self._task_count,
                "completed": self._completed_count,
                "failed": self._failed_count,
                "pending": self._queue.qsize(),
                "success_rate": self._completed_count / self._task_count
                if self._task_count > 0
                else 0,
            }


class ConcurrentScraperManager:
    """
    Manager for concurrent scraper execution.

    Coordinates multiple scrapers running in parallel with resource management.
    Target: 3+ simultaneous scraper operations with <500MB memory usage.
    """

    DEFAULT_MAX_WORKERS = 3
    DEFAULT_RATE_LIMIT = 2.0  # requests per second per worker

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        memory_limit_mb: float = 500.0,
        enable_browser_pool: bool = True,
        profiler: PerformanceProfiler | None = None,
    ):
        """
        Initialize the concurrent scraper manager.

        Args:
            max_workers: Maximum concurrent workers
            rate_limit: Requests per second limit
            memory_limit_mb: Memory limit before throttling (default 500MB for large scrapes)
            enable_browser_pool: Whether to use browser pooling
            profiler: Optional performance profiler
        """
        self.max_workers = max_workers
        self.rate_limit = rate_limit
        self.memory_limit_mb = memory_limit_mb
        self.enable_browser_pool = enable_browser_pool

        self._profiler = profiler
        self._task_queue = TaskQueue()
        self._throttler = ResourceThrottler(
            max_concurrent=max_workers,
            requests_per_second=rate_limit * max_workers,
            memory_limit_mb=memory_limit_mb,
        )

        self._browser_pool: BrowserPool | None = None
        self._executor: ThreadPoolExecutor | None = None

        self._worker_stats: dict[int, WorkerStats] = {}
        self._lock = threading.Lock()

        self._running = False
        self._start_time: float | None = None
        self._peak_concurrent = 0
        self._current_concurrent = 0

        self._stop_event = threading.Event()
        self._results: dict[str, ScrapingTask] = {}

    def initialize(
        self,
        browser_factory: Callable[[], Any] | None = None,
        browser_reset: Callable[[Any], None] | None = None,
    ) -> None:
        """
        Initialize the manager with browser factory.

        Args:
            browser_factory: Function to create browsers
            browser_reset: Function to reset browser state
        """
        if self.enable_browser_pool and browser_factory:
            self._browser_pool = BrowserPool(
                pool_size=self.max_workers,
                browser_factory=browser_factory,
                browser_reset=browser_reset,
            )
            self._browser_pool.initialize()

        # Initialize worker stats
        for i in range(self.max_workers):
            self._worker_stats[i] = WorkerStats(worker_id=i)

        logger.info(f"ConcurrentScraperManager initialized with {self.max_workers} workers")

    def submit_tasks(
        self,
        tasks: list[tuple[str, str]],  # List of (scraper_name, sku)
        priority: int = 0,
    ) -> list[str]:
        """
        Submit multiple scraping tasks.

        Args:
            tasks: List of (scraper_name, sku) tuples
            priority: Priority level (higher = more urgent)

        Returns:
            List of task IDs
        """
        task_ids = []

        for scraper_name, sku in tasks:
            task_id = f"{scraper_name}_{sku}_{int(time.time() * 1000)}"
            task = ScrapingTask(
                task_id=task_id,
                scraper_name=scraper_name,
                sku=sku,
                priority=priority,
            )
            self._task_queue.put(task)
            task_ids.append(task_id)

        logger.info(f"Submitted {len(task_ids)} tasks to queue")
        return task_ids

    def execute(
        self,
        task_executor: Callable[[str, str, Any | None], dict[str, Any]],
        on_task_complete: Callable[[ScrapingTask], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ConcurrencyStats:
        """
        Execute all queued tasks.

        Args:
            task_executor: Function to execute a single task
                          Signature: (scraper_name, sku, browser) -> result
            on_task_complete: Callback when a task completes
            on_progress: Callback for progress updates (completed, total)

        Returns:
            Execution statistics
        """
        if self._running:
            raise RuntimeError("Manager is already running")

        self._running = True
        self._start_time = time.time()
        self._stop_event.clear()

        total_tasks = self._task_queue.qsize()

        if total_tasks == 0:
            logger.warning("No tasks in queue")
            return self._generate_stats(total_tasks)

        logger.info(f"Starting execution of {total_tasks} tasks with {self.max_workers} workers")

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                self._executor = executor
                futures: dict[Future, ScrapingTask] = {}

                # Submit initial batch of tasks
                while not self._task_queue.empty() and len(futures) < self.max_workers:
                    task = self._task_queue.get(block=False)
                    future = executor.submit(
                        self._execute_task,
                        task,
                        task_executor,
                    )
                    futures[future] = task

                # Process completions and submit new tasks
                completed = 0
                while futures:
                    if self._stop_event.is_set():
                        logger.info("Stop requested, cancelling remaining tasks")
                        break

                    # Wait for any task to complete
                    done_futures = []
                    for future in as_completed(futures, timeout=1.0):
                        done_futures.append(future)
                        task = futures[future]

                        try:
                            task = future.result()
                            self._results[task.task_id] = task

                            if task.status == TaskStatus.COMPLETED:
                                self._task_queue.mark_completed(success=True)
                            else:
                                self._task_queue.mark_completed(success=False)

                            if on_task_complete:
                                on_task_complete(task)

                        except Exception as e:
                            task.status = TaskStatus.FAILED
                            task.error = e
                            self._task_queue.mark_completed(success=False)
                            logger.error(f"Task {task.task_id} failed: {e}")

                        completed += 1
                        if on_progress:
                            on_progress(completed, total_tasks)

                    # Remove completed futures and submit new tasks
                    for future in done_futures:
                        del futures[future]

                        if not self._task_queue.empty() and not self._stop_event.is_set():
                            try:
                                new_task = self._task_queue.get(block=False)
                                new_future = executor.submit(
                                    self._execute_task,
                                    new_task,
                                    task_executor,
                                )
                                futures[new_future] = new_task
                            except queue.Empty:
                                pass

        finally:
            self._running = False
            self._executor = None

        return self._generate_stats(total_tasks)

    def _execute_task(
        self,
        task: ScrapingTask,
        task_executor: Callable[[str, str, Any | None], dict[str, Any]],
    ) -> ScrapingTask:
        """Execute a single task with resource management."""
        worker_id = threading.current_thread().ident or 0
        worker_stat = self._get_worker_stat(worker_id)
        worker_stat.is_idle = False
        worker_stat.current_task = task.task_id

        # Update concurrent count
        with self._lock:
            self._current_concurrent += 1
            self._peak_concurrent = max(self._peak_concurrent, self._current_concurrent)

        task.start_time = time.time()
        task.status = TaskStatus.RUNNING

        # Record pending status
        supabase_sync.record_scrape_status(
            sku=task.sku, scraper_name=task.scraper_name, status="pending"
        )

        try:
            # Acquire resources
            with self._throttler.acquire(timeout=60.0) as acquired:
                if not acquired:
                    raise TimeoutError("Could not acquire resources")

                # Get browser if pool available
                browser = None
                if self._browser_pool:
                    with self._browser_pool.get_browser() as browser:
                        result = task_executor(task.scraper_name, task.sku, browser)
                else:
                    result = task_executor(task.scraper_name, task.sku, None)

                task.result = result
                task.status = TaskStatus.COMPLETED

                # Record success status
                supabase_sync.record_scrape_status(
                    sku=task.sku, scraper_name=task.scraper_name, status="scraped"
                )

        except Exception as e:
            task.error = e
            task.status = TaskStatus.FAILED

            # Record error status
            supabase_sync.record_scrape_status(
                sku=task.sku,
                scraper_name=task.scraper_name,
                status="error",
                error_message=str(e),
            )

            # Retry if allowed
            if task.retries < task.max_retries:
                task.retries += 1
                task.status = TaskStatus.PENDING
                self._task_queue.put(task)
                logger.warning(f"Retrying task {task.task_id} (attempt {task.retries})")

        finally:
            task.end_time = time.time()

            # Update worker stats
            duration_ms = (task.end_time - task.start_time) * 1000
            worker_stat.total_time_ms += duration_ms
            if task.status == TaskStatus.COMPLETED:
                worker_stat.tasks_completed += 1
            else:
                worker_stat.tasks_failed += 1
            worker_stat.is_idle = True
            worker_stat.current_task = None

            # Update concurrent count
            with self._lock:
                self._current_concurrent -= 1

            # Profile if enabled
            if self._profiler:
                self._profiler.record(
                    OperationType.TOTAL_SKU,
                    duration_ms,
                    f"{task.scraper_name}_{task.sku}",
                    {"success": task.status == TaskStatus.COMPLETED},
                    success=task.status == TaskStatus.COMPLETED,
                )

        return task

    def _get_worker_stat(self, thread_id: int) -> WorkerStats:
        """Get or create worker stats for a thread."""
        with self._lock:
            if thread_id not in self._worker_stats:
                worker_id = len(self._worker_stats)
                self._worker_stats[thread_id] = WorkerStats(worker_id=worker_id)
            return self._worker_stats[thread_id]

    def _generate_stats(self, total_tasks: int) -> ConcurrencyStats:
        """Generate execution statistics."""
        queue_stats = self._task_queue.get_stats()
        duration_ms = (time.time() - self._start_time) * 1000 if self._start_time else 0

        completed = queue_stats["completed"]
        tasks_per_second = completed / (duration_ms / 1000) if duration_ms > 0 else 0

        return ConcurrencyStats(
            total_tasks=total_tasks,
            completed_tasks=completed,
            failed_tasks=queue_stats["failed"],
            pending_tasks=queue_stats["pending"],
            active_workers=self._current_concurrent,
            peak_concurrent=self._peak_concurrent,
            total_duration_ms=duration_ms,
            tasks_per_second=tasks_per_second,
            worker_stats=list(self._worker_stats.values()),
        )

    def stop(self) -> None:
        """Request graceful stop of execution."""
        logger.info("Stopping concurrent scraper manager...")
        self._stop_event.set()

    def shutdown(self) -> None:
        """Shutdown the manager and release resources."""
        self.stop()

        if self._browser_pool:
            self._browser_pool.shutdown()

        logger.info("ConcurrentScraperManager shutdown complete")

    def get_stats(self) -> dict[str, Any]:
        """Get current manager statistics."""
        stats = {
            "running": self._running,
            "max_workers": self.max_workers,
            "current_concurrent": self._current_concurrent,
            "peak_concurrent": self._peak_concurrent,
            "queue": self._task_queue.get_stats(),
            "throttler": self._throttler.get_stats(),
        }

        if self._browser_pool:
            stats["browser_pool"] = self._browser_pool.get_stats()

        return stats

    def get_results(self) -> dict[str, ScrapingTask]:
        """Get all task results."""
        return self._results.copy()


def create_concurrent_manager(
    max_workers: int = 3,
    rate_limit: float = 2.0,
    memory_limit_mb: float = 200.0,
) -> ConcurrentScraperManager:
    """
    Factory function to create a concurrent scraper manager.

    Args:
        max_workers: Maximum concurrent workers
        rate_limit: Requests per second limit
        memory_limit_mb: Memory limit

    Returns:
        Configured ConcurrentScraperManager
    """
    return ConcurrentScraperManager(
        max_workers=max_workers,
        rate_limit=rate_limit,
        memory_limit_mb=memory_limit_mb,
    )
