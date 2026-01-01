"""
Memory management and optimization utilities for scraper execution.

Provides memory tracking, leak detection, and optimization strategies
to achieve the target of <200MB peak memory usage.
"""

import gc
import logging
import os
import sys
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    import psutil

logger = logging.getLogger(__name__)

# Try to import psutil for accurate memory tracking
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not available, memory tracking will be limited")


class MemoryUnit(Enum):
    """Memory size units."""

    BYTES = 1
    KB = 1024
    MB = 1024 * 1024
    GB = 1024 * 1024 * 1024


@dataclass
class MemorySnapshot:
    """Snapshot of memory usage at a point in time."""

    timestamp: float
    rss_bytes: int  # Resident Set Size
    vms_bytes: int  # Virtual Memory Size
    heap_bytes: int  # Python heap size (approximate)
    gc_objects: int  # Number of tracked objects
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "rss_mb": round(self.rss_bytes / MemoryUnit.MB.value, 2),
            "vms_mb": round(self.vms_bytes / MemoryUnit.MB.value, 2),
            "heap_mb": round(self.heap_bytes / MemoryUnit.MB.value, 2),
            "gc_objects": self.gc_objects,
            "label": self.label,
        }


@dataclass
class MemoryReport:
    """Complete memory usage report."""

    start_snapshot: MemorySnapshot
    end_snapshot: MemorySnapshot
    peak_rss_bytes: int
    snapshots: list[MemorySnapshot]
    warnings: list[str]
    recommendations: list[str]

    @property
    def memory_growth_bytes(self) -> int:
        """Calculate memory growth during the session."""
        return self.end_snapshot.rss_bytes - self.start_snapshot.rss_bytes

    @property
    def peak_rss_mb(self) -> float:
        """Peak RSS in megabytes."""
        return self.peak_rss_bytes / MemoryUnit.MB.value

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start": self.start_snapshot.to_dict(),
            "end": self.end_snapshot.to_dict(),
            "peak_rss_mb": round(self.peak_rss_mb, 2),
            "memory_growth_mb": round(self.memory_growth_bytes / MemoryUnit.MB.value, 2),
            "snapshot_count": len(self.snapshots),
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class MemoryManager:
    """
    Memory manager for tracking and optimizing memory usage.

    Provides memory monitoring, threshold alerts, and garbage collection control.
    Target: <500MB peak memory usage for large-scale scrapes.
    """

    # Target thresholds (updated for large-scale scrapes)
    TARGET_PEAK_MB = 500
    WARNING_THRESHOLD_MB = 350
    CRITICAL_THRESHOLD_MB = 450
    AGGRESSIVE_GC_THRESHOLD_MB = 300  # Trigger aggressive GC above this

    def __init__(
        self,
        enable_monitoring: bool = True,
        snapshot_interval_seconds: float = 5.0,
        auto_gc_threshold_mb: float = 100.0,
    ) -> None:
        """
        Initialize the memory manager.

        Args:
            enable_monitoring: Whether to enable background monitoring
            snapshot_interval_seconds: Interval between automatic snapshots
            auto_gc_threshold_mb: Memory threshold for automatic GC trigger
        """
        self.enable_monitoring = enable_monitoring
        self.snapshot_interval = snapshot_interval_seconds
        self.auto_gc_threshold_mb = auto_gc_threshold_mb

        self._snapshots: deque[MemorySnapshot] = deque(maxlen=1000)
        self._peak_rss_bytes: int = 0
        self._start_snapshot: MemorySnapshot | None = None
        self._lock = threading.Lock()

        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None

        self._callbacks: list[Callable[[MemorySnapshot], None]] = []

        # Get process handle if psutil available
        self._process: psutil.Process | None = psutil.Process(os.getpid()) if HAS_PSUTIL else None

    def start_session(self) -> None:
        """Start a memory monitoring session."""
        with self._lock:
            self._snapshots.clear()
            self._peak_rss_bytes = 0

            # Take initial snapshot
            self._start_snapshot = self._take_snapshot("session_start")
            self._snapshots.append(self._start_snapshot)
            self._peak_rss_bytes = self._start_snapshot.rss_bytes

        # Start background monitoring if enabled
        if self.enable_monitoring and not self._monitoring:
            self._monitoring = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True, name="MemoryMonitor"
            )
            self._monitor_thread.start()

        logger.info(
            f"Memory session started. Initial RSS: "
            f"{self._start_snapshot.rss_bytes / MemoryUnit.MB.value:.2f}MB"
        )

    def end_session(self) -> MemoryReport:
        """
        End the monitoring session and generate report.

        Returns:
            MemoryReport with analysis and recommendations
        """
        # Stop monitoring
        self._monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)

        # Take final snapshot
        end_snapshot = self._take_snapshot("session_end")

        with self._lock:
            self._snapshots.append(end_snapshot)
            snapshots = list(self._snapshots)
            peak_rss = self._peak_rss_bytes
            start = self._start_snapshot or end_snapshot

        # Analyze and generate report
        warnings = self._analyze_warnings(snapshots, peak_rss)
        recommendations = self._generate_recommendations(snapshots, peak_rss)

        report = MemoryReport(
            start_snapshot=start,
            end_snapshot=end_snapshot,
            peak_rss_bytes=peak_rss,
            snapshots=snapshots,
            warnings=warnings,
            recommendations=recommendations,
        )

        logger.info(
            f"Memory session ended. Peak RSS: {report.peak_rss_mb:.2f}MB, "
            f"Growth: {report.memory_growth_bytes / MemoryUnit.MB.value:.2f}MB"
        )

        return report

    def take_snapshot(self, label: str = "") -> MemorySnapshot:
        """
        Take a memory snapshot.

        Args:
            label: Optional label for the snapshot

        Returns:
            MemorySnapshot with current memory state
        """
        snapshot = self._take_snapshot(label)

        with self._lock:
            self._snapshots.append(snapshot)
            if snapshot.rss_bytes > self._peak_rss_bytes:
                self._peak_rss_bytes = snapshot.rss_bytes

        # Check thresholds and trigger callbacks
        self._check_thresholds(snapshot)

        return snapshot

    def _take_snapshot(self, label: str = "") -> MemorySnapshot:
        """Internal method to create a memory snapshot."""
        timestamp = time.time()
        gc_objects = len(gc.get_objects())

        if self._process and HAS_PSUTIL:
            mem_info = self._process.memory_info()
            rss_bytes = mem_info.rss
            vms_bytes = mem_info.vms
        else:
            # Fallback to sys.getsizeof approximation
            rss_bytes = sum(sys.getsizeof(obj) for obj in gc.get_objects()[:1000])
            vms_bytes = rss_bytes

        # Approximate heap size
        heap_bytes = sum(sys.getsizeof(obj) for obj in gc.get_objects()[:100]) * (gc_objects / 100)

        return MemorySnapshot(
            timestamp=timestamp,
            rss_bytes=rss_bytes,
            vms_bytes=vms_bytes,
            heap_bytes=int(heap_bytes),
            gc_objects=gc_objects,
            label=label,
        )

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._monitoring:
            time.sleep(self.snapshot_interval)
            if self._monitoring:  # Check again after sleep
                try:
                    self.take_snapshot("auto_monitor")
                except Exception as e:
                    logger.debug(f"Error taking snapshot: {e}")

    def _check_thresholds(self, snapshot: MemorySnapshot) -> None:
        """Check memory thresholds and take action."""
        rss_mb = snapshot.rss_bytes / MemoryUnit.MB.value

        if rss_mb >= self.CRITICAL_THRESHOLD_MB:
            logger.warning(
                f"CRITICAL: Memory usage at {rss_mb:.2f}MB "
                f"(threshold: {self.CRITICAL_THRESHOLD_MB}MB)"
            )
            self.aggressive_cleanup()
            for callback in self._callbacks:
                try:
                    callback(snapshot)
                except Exception as e:
                    logger.debug(f"Callback error: {e}")

        elif rss_mb >= self.AGGRESSIVE_GC_THRESHOLD_MB:
            logger.info(
                f"Memory at {rss_mb:.2f}MB, triggering aggressive GC "
                f"(threshold: {self.AGGRESSIVE_GC_THRESHOLD_MB}MB)"
            )
            self.force_gc()

        elif rss_mb >= self.WARNING_THRESHOLD_MB:
            logger.warning(
                f"WARNING: Memory usage at {rss_mb:.2f}MB "
                f"(threshold: {self.WARNING_THRESHOLD_MB}MB)"
            )

        # Auto GC if threshold exceeded
        if rss_mb >= self.auto_gc_threshold_mb:
            self.trigger_gc()

    def aggressive_cleanup(self) -> None:
        """
        Perform aggressive memory cleanup for large-scale scrapes.

        This includes:
        - Full garbage collection across all generations
        - Clearing internal caches
        - Compacting memory if possible
        """
        logger.info("Performing aggressive memory cleanup...")

        # Clear any internal caches
        self._snapshots.clear()

        # Force full GC multiple times
        collected_total = 0
        for _ in range(3):
            collected = gc.collect()
            collected_total += collected

        # Try to release memory back to OS (Python 3.9+)
        try:
            import ctypes

            if hasattr(ctypes, "pythonapi"):
                ctypes.pythonapi.PyMem_SetupDebugHooks()
        except Exception:
            pass

        logger.info(f"Aggressive cleanup collected {collected_total} objects")

    def _analyze_warnings(
        self,
        snapshots: list[MemorySnapshot],
        peak_rss: int,
    ) -> list[str]:
        """Analyze snapshots and generate warnings."""
        warnings = []
        peak_mb = peak_rss / MemoryUnit.MB.value

        if peak_mb >= self.TARGET_PEAK_MB:
            warnings.append(
                f"Peak memory ({peak_mb:.2f}MB) exceeded target ({self.TARGET_PEAK_MB}MB)"
            )

        if peak_mb >= self.CRITICAL_THRESHOLD_MB:
            warnings.append(
                f"Critical memory threshold ({self.CRITICAL_THRESHOLD_MB}MB) was reached"
            )

        # Check for memory leaks (steady growth pattern)
        if len(snapshots) >= 10:
            growth_rates = []
            for i in range(1, min(10, len(snapshots))):
                rate = snapshots[i].rss_bytes - snapshots[i - 1].rss_bytes
                growth_rates.append(rate)

            avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0
            if avg_growth > 1 * MemoryUnit.MB.value:  # Growing >1MB per snapshot
                warnings.append(
                    f"Possible memory leak: average growth of "
                    f"{avg_growth / MemoryUnit.MB.value:.2f}MB per snapshot"
                )

        # Check for high object count
        if snapshots:
            max_objects = max(s.gc_objects for s in snapshots)
            if max_objects > 500000:
                warnings.append(
                    f"High object count detected ({max_objects:,} objects). "
                    "Consider optimizing data structures."
                )

        return warnings

    def _generate_recommendations(
        self,
        snapshots: list[MemorySnapshot],
        peak_rss: int,
    ) -> list[str]:
        """Generate optimization recommendations."""
        recommendations = []
        peak_mb = peak_rss / MemoryUnit.MB.value

        if peak_mb > self.TARGET_PEAK_MB:
            recommendations.append(
                "Use streaming/iterators instead of loading all data into memory"
            )
            recommendations.append("Consider processing results in smaller batches")

        if snapshots:
            max_objects = max(s.gc_objects for s in snapshots)
            if max_objects > 100000:
                recommendations.append("Use __slots__ in data classes to reduce memory overhead")
                recommendations.append(
                    "Consider using generators instead of lists for large datasets"
                )

            # Check heap vs RSS ratio
            avg_heap_ratio = sum(
                s.heap_bytes / s.rss_bytes if s.rss_bytes > 0 else 0 for s in snapshots
            ) / len(snapshots)

            if avg_heap_ratio > 0.8:
                recommendations.append(
                    "High Python heap usage. Consider using numpy arrays for large datasets."
                )

        if not recommendations:
            recommendations.append("Memory usage is within acceptable limits.")

        return recommendations

    def register_callback(
        self,
        callback: Callable[[MemorySnapshot], None],
    ) -> None:
        """
        Register a callback for memory threshold alerts.

        Args:
            callback: Function called when thresholds are exceeded
        """
        self._callbacks.append(callback)

    def trigger_gc(self) -> int:
        """
        Trigger garbage collection.

        Returns:
            Number of unreachable objects found
        """
        return gc.collect()

    def force_gc(self) -> tuple[int, int, int]:
        """
        Force full garbage collection across all generations.

        Returns:
            Tuple of unreachable objects found in each generation
        """
        result = (gc.collect(0), gc.collect(1), gc.collect(2))
        logger.debug(f"Forced GC: gen0={result[0]}, gen1={result[1]}, gen2={result[2]}")
        return result

    def get_current_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        if self._process and HAS_PSUTIL:
            return float(self._process.memory_info().rss / MemoryUnit.MB.value)
        return 0.0

    def is_within_target(self) -> bool:
        """Check if current memory usage is within target."""
        return self.get_current_usage_mb() < self.TARGET_PEAK_MB


# Type variable for generic classes
T = TypeVar("T")


class StreamingIterator(Generic[T]):
    """
    Memory-efficient iterator for processing large datasets.

    Processes items one at a time without loading entire dataset.
    """

    def __init__(
        self,
        source: Iterator[T],
        batch_size: int = 100,
        on_batch_complete: Callable[[int], None] | None = None,
    ) -> None:
        """
        Initialize the streaming iterator.

        Args:
            source: Source iterator
            batch_size: Items per batch (for progress tracking)
            on_batch_complete: Callback when batch completes
        """
        self._source = source
        self._batch_size = batch_size
        self._on_batch_complete = on_batch_complete
        self._processed = 0

    def __iter__(self) -> Iterator[T]:
        """Return self as iterator."""
        return self

    def __next__(self) -> T:
        """Get next item."""
        item = next(self._source)
        self._processed += 1

        if self._processed % self._batch_size == 0:
            # Trigger GC periodically
            gc.collect(0)
            if self._on_batch_complete:
                self._on_batch_complete(self._processed)

        return item

    @property
    def processed_count(self) -> int:
        """Number of items processed."""
        return self._processed


class ChunkedProcessor(Generic[T]):
    """
    Process large datasets in memory-efficient chunks.

    Loads and processes data in chunks to limit memory usage.
    """

    def __init__(
        self,
        chunk_size: int = 100,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        """
        Initialize the chunked processor.

        Args:
            chunk_size: Number of items per chunk
            memory_manager: Optional memory manager for tracking
        """
        self.chunk_size = chunk_size
        self._memory_manager = memory_manager

    def process_chunks(
        self,
        items: list[T],
        processor: Callable[[list[T]], list[Any]],
    ) -> Iterator[Any]:
        """
        Process items in chunks.

        Args:
            items: Items to process
            processor: Function to process each chunk

        Yields:
            Processed results from each chunk
        """
        total_items = len(items)

        for i in range(0, total_items, self.chunk_size):
            chunk = items[i : i + self.chunk_size]

            # Process chunk
            results = processor(chunk)

            # Yield results
            yield from results

            # Clear chunk reference and collect garbage
            del chunk
            gc.collect(0)

            if self._memory_manager:
                self._memory_manager.take_snapshot(f"chunk_{i // self.chunk_size}")

            logger.debug(
                f"Processed chunk {i // self.chunk_size + 1}/"
                f"{(total_items + self.chunk_size - 1) // self.chunk_size}"
            )

    def process_streaming(
        self,
        source: Iterator[T],
        processor: Callable[[T], Any],
    ) -> Iterator[Any]:
        """
        Process items from a streaming source.

        Args:
            source: Iterator providing items
            processor: Function to process each item

        Yields:
            Processed results
        """
        batch: list[T] = []

        for item in source:
            result = processor(item)
            yield result

            batch.append(item)
            if len(batch) >= self.chunk_size:
                batch.clear()
                gc.collect(0)


class ObjectPool(Generic[T]):
    """
    Object pool for reusing expensive-to-create objects.

    Reduces memory allocation overhead by reusing objects.
    """

    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 10,
        reset_func: Callable[[T], None] | None = None,
    ) -> None:
        """
        Initialize the object pool.

        Args:
            factory: Function to create new objects
            max_size: Maximum pool size
            reset_func: Optional function to reset objects before reuse
        """
        self._factory = factory
        self._max_size = max_size
        self._reset_func = reset_func
        self._pool: deque[T] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._created = 0
        self._reused = 0

    def acquire(self) -> T:
        """
        Acquire an object from the pool.

        Returns:
            Object from pool or newly created
        """
        with self._lock:
            if self._pool:
                obj = self._pool.pop()
                self._reused += 1
                return obj

            self._created += 1
            return self._factory()

    def release(self, obj: T) -> None:
        """
        Release an object back to the pool.

        Args:
            obj: Object to return to pool
        """
        with self._lock:
            if len(self._pool) < self._max_size:
                if self._reset_func:
                    try:
                        self._reset_func(obj)
                    except Exception:
                        return  # Don't pool if reset fails

                self._pool.append(obj)

    @contextmanager
    def get(self) -> Iterator[T]:
        """
        Context manager for acquiring and releasing objects.

        Yields:
            Pooled object
        """
        obj = self.acquire()
        try:
            yield obj
        finally:
            self.release(obj)

    def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "max_size": self._max_size,
                "created": self._created,
                "reused": self._reused,
                "reuse_rate": self._reused / (self._created + self._reused)
                if (self._created + self._reused) > 0
                else 0,
            }

    def clear(self) -> None:
        """Clear the pool."""
        with self._lock:
            self._pool.clear()


class WeakCache(Generic[T]):
    """
    Weak reference cache that allows garbage collection.

    Caches objects without preventing their garbage collection.
    """

    def __init__(self, max_size: int = 1000) -> None:
        """
        Initialize the weak cache.

        Args:
            max_size: Maximum number of cached items
        """
        self._cache: dict[str, weakref.ref[T]] = {}
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> T | None:
        """
        Get item from cache.

        Args:
            key: Cache key

        Returns:
            Cached item or None if not found/collected
        """
        with self._lock:
            ref = self._cache.get(key)
            if ref is not None:
                obj = ref()
                if obj is not None:
                    self._hits += 1
                    return obj
                else:
                    # Object was garbage collected
                    del self._cache[key]

            self._misses += 1
            return None

    def set(self, key: str, value: T) -> None:
        """
        Set item in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            # Cleanup dead references if at max size
            if len(self._cache) >= self._max_size:
                self._cleanup()

            try:
                self._cache[key] = weakref.ref(value)
            except TypeError:
                # Object doesn't support weak references
                pass

    def _cleanup(self) -> None:
        """Remove dead references."""
        dead_keys = [key for key, ref in self._cache.items() if ref() is None]
        for key in dead_keys:
            del self._cache[key]

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            self._cleanup()
            total_accesses = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total_accesses if total_accesses > 0 else 0,
            }


@dataclass
class MemoryEfficientResult:
    """
    Memory-efficient result container using __slots__.

    Uses __slots__ to reduce memory overhead compared to regular classes.
    """

    __slots__ = ["data", "sku", "source", "timestamp"]

    sku: str
    source: str
    data: dict[str, Any]
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sku": self.sku,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
        }


def get_object_size(obj: Any, seen: set | None = None) -> int:
    """
    Recursively calculate total size of an object.

    Args:
        obj: Object to measure
        seen: Set of already-seen object ids (for cycle detection)

    Returns:
        Total size in bytes
    """
    size = sys.getsizeof(obj)

    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0

    seen.add(obj_id)

    if isinstance(obj, dict):
        size += sum(get_object_size(k, seen) + get_object_size(v, seen) for k, v in obj.items())
    elif hasattr(obj, "__dict__"):
        size += get_object_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray)):
        try:
            size += sum(get_object_size(i, seen) for i in obj)
        except TypeError:
            pass

    return size


def format_bytes(size_bytes: float) -> str:
    """
    Format bytes to human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


# Global memory manager instance
_global_memory_manager: MemoryManager | None = None
_global_lock = threading.Lock()


def get_memory_manager() -> MemoryManager:
    """
    Get or create the global memory manager.

    Returns:
        MemoryManager instance
    """
    global _global_memory_manager
    with _global_lock:
        if _global_memory_manager is None:
            _global_memory_manager = MemoryManager()
        return _global_memory_manager


@contextmanager
def memory_tracking(label: str = ""):
    """
    Context manager for tracking memory usage of a code block.

    Args:
        label: Label for the tracking session

    Yields:
        MemoryManager instance

    Example:
        with memory_tracking("data_processing") as mm:
            process_large_dataset()
        print(f"Peak memory: {mm.get_current_usage_mb()}MB")
    """
    mm = MemoryManager(enable_monitoring=False)
    mm.start_session()

    if label:
        mm.take_snapshot(f"{label}_start")

    try:
        yield mm
    finally:
        if label:
            mm.take_snapshot(f"{label}_end")

        report = mm.end_session()
        if report.warnings:
            for warning in report.warnings:
                logger.warning(f"Memory tracking [{label}]: {warning}")
