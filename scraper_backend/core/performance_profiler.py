"""
Performance profiling and optimization utilities for scraper execution.

Provides timing analysis, bottleneck identification, and optimization recommendations
to achieve the target of <2min average execution time.
"""

import functools
import logging
import statistics
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Types of operations that can be profiled."""

    BROWSER_INIT = "browser_init"
    NAVIGATION = "navigation"
    WAIT = "wait"
    EXTRACTION = "extraction"
    CLICK = "click"
    INPUT = "input"
    WORKFLOW_STEP = "workflow_step"
    TOTAL_SKU = "total_sku"
    TOTAL_WORKFLOW = "total_workflow"


@dataclass
class TimingRecord:
    """Record of a single timed operation."""

    operation_type: OperationType
    operation_name: str
    duration_ms: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True


@dataclass
class OperationStats:
    """Statistics for a specific operation type."""

    operation_type: OperationType
    count: int
    total_ms: float
    min_ms: float
    max_ms: float
    avg_ms: float
    std_dev_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    success_rate: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation_type": self.operation_type.value,
            "count": self.count,
            "total_ms": round(self.total_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
            "std_dev_ms": round(self.std_dev_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "success_rate": round(self.success_rate, 4),
        }


@dataclass
class PerformanceReport:
    """Complete performance report for a profiling session."""

    session_id: str
    start_time: float
    end_time: float
    total_duration_ms: float
    operation_stats: dict[OperationType, OperationStats]
    bottlenecks: list[dict[str, Any]]
    recommendations: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "total_duration_sec": round(self.total_duration_ms / 1000, 2),
            "operation_stats": {
                op_type.value: stats.to_dict() for op_type, stats in self.operation_stats.items()
            },
            "bottlenecks": self.bottlenecks,
            "recommendations": self.recommendations,
            "metadata": self.metadata,
        }


class PerformanceProfiler:
    """
    Performance profiler for scraper operations.

    Tracks timing of all operations and provides analysis for optimization.
    Thread-safe for use in concurrent scraping scenarios.
    """

    # Target thresholds (in milliseconds)
    TARGET_SKU_TIME_MS = 120000  # 2 minutes per SKU max
    TARGET_NAVIGATION_MS = 10000  # 10 seconds for navigation
    TARGET_EXTRACTION_MS = 5000  # 5 seconds for extraction
    TARGET_WAIT_MS = 5000  # 5 seconds for waits

    def __init__(self, session_id: str | None = None):
        """
        Initialize the performance profiler.

        Args:
            session_id: Optional session identifier for tracking
        """
        self.session_id = session_id or f"profile_{int(time.time() * 1000)}"
        self._records: list[TimingRecord] = []
        self._lock = threading.Lock()
        self._start_time: float | None = None
        self._end_time: float | None = None
        self._active_timers: dict[str, float] = {}

    def start_session(self) -> None:
        """Start a profiling session."""
        with self._lock:
            self._start_time = time.time()
            self._records.clear()
            self._active_timers.clear()
        logger.debug(f"Started profiling session: {self.session_id}")

    def end_session(self) -> None:
        """End the profiling session."""
        with self._lock:
            self._end_time = time.time()
        logger.debug(f"Ended profiling session: {self.session_id}")

    @contextmanager
    def profile(
        self,
        operation_type: OperationType,
        operation_name: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        """
        Context manager for profiling an operation.

        Args:
            operation_type: Type of operation being profiled
            operation_name: Optional name for the specific operation
            metadata: Optional metadata to attach to the record

        Yields:
            None

        Example:
            with profiler.profile(OperationType.NAVIGATION, "amazon_search"):
                browser.get(url)
        """
        start_time = time.perf_counter()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            record = TimingRecord(
                operation_type=operation_type,
                operation_name=operation_name or operation_type.value,
                duration_ms=duration_ms,
                timestamp=time.time(),
                metadata=metadata or {},
                success=success,
            )

            with self._lock:
                self._records.append(record)

            # Log slow operations
            self._check_and_log_slow_operation(record)

    def start_timer(self, timer_id: str) -> None:
        """
        Start a named timer for manual timing.

        Args:
            timer_id: Unique identifier for this timer
        """
        with self._lock:
            self._active_timers[timer_id] = time.perf_counter()

    def stop_timer(
        self,
        timer_id: str,
        operation_type: OperationType,
        operation_name: str = "",
        metadata: dict[str, Any] | None = None,
        success: bool = True,
    ) -> float:
        """
        Stop a named timer and record the result.

        Args:
            timer_id: Identifier of the timer to stop
            operation_type: Type of operation that was timed
            operation_name: Optional name for the operation
            metadata: Optional metadata to attach
            success: Whether the operation succeeded

        Returns:
            Duration in milliseconds
        """
        end_time = time.perf_counter()

        with self._lock:
            start_time = self._active_timers.pop(timer_id, None)

        if start_time is None:
            logger.warning(f"Timer {timer_id} was not started")
            return 0.0

        duration_ms = (end_time - start_time) * 1000

        record = TimingRecord(
            operation_type=operation_type,
            operation_name=operation_name or operation_type.value,
            duration_ms=duration_ms,
            timestamp=time.time(),
            metadata=metadata or {},
            success=success,
        )

        with self._lock:
            self._records.append(record)

        self._check_and_log_slow_operation(record)
        return duration_ms

    def record(
        self,
        operation_type: OperationType,
        duration_ms: float,
        operation_name: str = "",
        metadata: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        """
        Manually record a timing measurement.

        Args:
            operation_type: Type of operation
            duration_ms: Duration in milliseconds
            operation_name: Optional name for the operation
            metadata: Optional metadata to attach
            success: Whether the operation succeeded
        """
        record = TimingRecord(
            operation_type=operation_type,
            operation_name=operation_name or operation_type.value,
            duration_ms=duration_ms,
            timestamp=time.time(),
            metadata=metadata or {},
            success=success,
        )

        with self._lock:
            self._records.append(record)

        self._check_and_log_slow_operation(record)

    def _check_and_log_slow_operation(self, record: TimingRecord) -> None:
        """Check if an operation is slow and log a warning."""
        thresholds = {
            OperationType.NAVIGATION: self.TARGET_NAVIGATION_MS,
            OperationType.EXTRACTION: self.TARGET_EXTRACTION_MS,
            OperationType.WAIT: self.TARGET_WAIT_MS,
            OperationType.TOTAL_SKU: self.TARGET_SKU_TIME_MS,
        }

        threshold = thresholds.get(record.operation_type)
        if threshold and record.duration_ms > threshold:
            logger.warning(
                f"Slow operation detected: {record.operation_name} took "
                f"{record.duration_ms:.2f}ms (threshold: {threshold}ms)"
            )

    def get_stats(self) -> dict[OperationType, OperationStats]:
        """
        Calculate statistics for all operation types.

        Returns:
            Dictionary mapping operation types to their statistics
        """
        with self._lock:
            records = self._records.copy()

        # Group records by operation type
        grouped: dict[OperationType, list[TimingRecord]] = defaultdict(list)
        for record in records:
            grouped[record.operation_type].append(record)

        stats: dict[OperationType, OperationStats] = {}
        for op_type, op_records in grouped.items():
            durations = [r.duration_ms for r in op_records]
            success_count = sum(1 for r in op_records if r.success)

            if not durations:
                continue

            sorted_durations = sorted(durations)
            n = len(durations)

            stats[op_type] = OperationStats(
                operation_type=op_type,
                count=n,
                total_ms=sum(durations),
                min_ms=min(durations),
                max_ms=max(durations),
                avg_ms=statistics.mean(durations),
                std_dev_ms=statistics.stdev(durations) if n > 1 else 0.0,
                p50_ms=sorted_durations[n // 2],
                p95_ms=sorted_durations[int(n * 0.95)] if n >= 20 else sorted_durations[-1],
                p99_ms=sorted_durations[int(n * 0.99)] if n >= 100 else sorted_durations[-1],
                success_rate=success_count / n if n > 0 else 0.0,
            )

        return stats

    def identify_bottlenecks(self) -> list[dict[str, Any]]:
        """
        Identify performance bottlenecks.

        Returns:
            List of identified bottlenecks with details
        """
        stats = self.get_stats()
        bottlenecks: list[dict[str, Any]] = []

        # Check each operation type against thresholds
        thresholds = {
            OperationType.NAVIGATION: self.TARGET_NAVIGATION_MS,
            OperationType.EXTRACTION: self.TARGET_EXTRACTION_MS,
            OperationType.WAIT: self.TARGET_WAIT_MS,
            OperationType.TOTAL_SKU: self.TARGET_SKU_TIME_MS,
        }

        for op_type, threshold in thresholds.items():
            if op_type in stats:
                op_stats = stats[op_type]
                if op_stats.avg_ms > threshold:
                    bottlenecks.append(
                        {
                            "type": "avg_exceeds_threshold",
                            "operation": op_type.value,
                            "avg_ms": op_stats.avg_ms,
                            "threshold_ms": threshold,
                            "severity": "high" if op_stats.avg_ms > threshold * 2 else "medium",
                            "impact_pct": (op_stats.total_ms / self._get_total_duration_ms()) * 100
                            if self._get_total_duration_ms() > 0
                            else 0,
                        }
                    )

        # Check for high variance operations
        for op_type, op_stats in stats.items():
            if op_stats.count >= 5 and op_stats.std_dev_ms > op_stats.avg_ms * 0.5:
                bottlenecks.append(
                    {
                        "type": "high_variance",
                        "operation": op_type.value,
                        "avg_ms": op_stats.avg_ms,
                        "std_dev_ms": op_stats.std_dev_ms,
                        "severity": "medium",
                    }
                )

        # Check for operations consuming most time
        total_ms = self._get_total_duration_ms()
        if total_ms > 0:
            for op_type, op_stats in stats.items():
                impact_pct = (op_stats.total_ms / total_ms) * 100
                if impact_pct > 40:  # Operation consumes >40% of total time
                    bottlenecks.append(
                        {
                            "type": "high_time_consumer",
                            "operation": op_type.value,
                            "total_ms": op_stats.total_ms,
                            "impact_pct": impact_pct,
                            "severity": "high" if impact_pct > 60 else "medium",
                        }
                    )

        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2}
        bottlenecks.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))

        return bottlenecks

    def get_recommendations(self) -> list[str]:
        """
        Generate optimization recommendations based on profiling data.

        Returns:
            List of actionable recommendations
        """
        stats = self.get_stats()
        bottlenecks = self.identify_bottlenecks()
        recommendations: list[str] = []

        # Navigation recommendations
        if OperationType.NAVIGATION in stats:
            nav_stats = stats[OperationType.NAVIGATION]
            if nav_stats.avg_ms > self.TARGET_NAVIGATION_MS:
                recommendations.append(
                    f"Navigation is slow (avg {nav_stats.avg_ms:.0f}ms). Consider: "
                    "1) Using a faster network connection, "
                    "2) Enabling browser caching, "
                    "3) Using lighter page load strategies (eager vs normal)"
                )

        # Wait recommendations
        if OperationType.WAIT in stats:
            wait_stats = stats[OperationType.WAIT]
            if wait_stats.total_ms > self._get_total_duration_ms() * 0.3:
                recommendations.append(
                    f"Waits consume {(wait_stats.total_ms / self._get_total_duration_ms()) * 100:.1f}% "
                    "of total time. Consider: "
                    "1) Using adaptive waits based on page state, "
                    "2) Reducing fixed wait times, "
                    "3) Using element visibility checks instead of sleep"
                )

        # Extraction recommendations
        if OperationType.EXTRACTION in stats:
            ext_stats = stats[OperationType.EXTRACTION]
            if ext_stats.avg_ms > self.TARGET_EXTRACTION_MS:
                recommendations.append(
                    f"Extraction is slow (avg {ext_stats.avg_ms:.0f}ms). Consider: "
                    "1) Using more specific CSS selectors, "
                    "2) Batching element lookups, "
                    "3) Using JavaScript execution for bulk extraction"
                )

        # High variance recommendations
        high_variance = [b for b in bottlenecks if b["type"] == "high_variance"]
        if high_variance:
            ops = ", ".join(b["operation"] for b in high_variance)
            recommendations.append(
                f"High timing variance detected in: {ops}. "
                "This may indicate unstable network or page loading issues. "
                "Consider adding retry logic with adaptive delays."
            )

        # Browser init recommendations
        if OperationType.BROWSER_INIT in stats:
            init_stats = stats[OperationType.BROWSER_INIT]
            if init_stats.count > 1 and init_stats.avg_ms > 5000:
                recommendations.append(
                    f"Browser initialization is slow (avg {init_stats.avg_ms:.0f}ms) "
                    f"and happening {init_stats.count} times. "
                    "Consider using browser pooling to reuse browser instances."
                )

        # Overall performance
        total_ms = self._get_total_duration_ms()
        sku_count = stats.get(
            OperationType.TOTAL_SKU,
            OperationStats(OperationType.TOTAL_SKU, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ).count

        if sku_count > 0 and total_ms / sku_count > self.TARGET_SKU_TIME_MS:
            avg_per_sku = total_ms / sku_count
            recommendations.append(
                f"Average time per SKU ({avg_per_sku:.0f}ms) exceeds target "
                f"({self.TARGET_SKU_TIME_MS}ms). Focus on the highest-impact bottlenecks first."
            )

        return recommendations

    def _get_total_duration_ms(self) -> float:
        """Get total session duration in milliseconds."""
        with self._lock:
            if self._start_time and self._end_time:
                return (self._end_time - self._start_time) * 1000
            elif self._start_time:
                return (time.time() - self._start_time) * 1000
            return sum(r.duration_ms for r in self._records)

    def generate_report(self) -> PerformanceReport:
        """
        Generate a complete performance report.

        Returns:
            PerformanceReport with all statistics and recommendations
        """
        with self._lock:
            start = self._start_time or (
                min(r.timestamp for r in self._records) if self._records else time.time()
            )
            end = self._end_time or time.time()

        return PerformanceReport(
            session_id=self.session_id,
            start_time=start,
            end_time=end,
            total_duration_ms=self._get_total_duration_ms(),
            operation_stats=self.get_stats(),
            bottlenecks=self.identify_bottlenecks(),
            recommendations=self.get_recommendations(),
            metadata={
                "record_count": len(self._records),
            },
        )

    def reset(self) -> None:
        """Reset the profiler for a new session."""
        with self._lock:
            self._records.clear()
            self._active_timers.clear()
            self._start_time = None
            self._end_time = None
        self.session_id = f"profile_{int(time.time() * 1000)}"


# Global profiler instance for convenient access
_global_profiler: PerformanceProfiler | None = None
_global_lock = threading.Lock()


def get_profiler(session_id: str | None = None) -> PerformanceProfiler:
    """
    Get or create the global profiler instance.

    Args:
        session_id: Optional session ID for a new profiler

    Returns:
        PerformanceProfiler instance
    """
    global _global_profiler
    with _global_lock:
        if _global_profiler is None or session_id:
            _global_profiler = PerformanceProfiler(session_id)
        return _global_profiler


def profile_operation(operation_type: OperationType, operation_name: str = "") -> Callable:
    """
    Decorator for profiling a function.

    Args:
        operation_type: Type of operation
        operation_name: Optional name for the operation

    Returns:
        Decorated function

    Example:
        @profile_operation(OperationType.EXTRACTION, "extract_price")
        def extract_price(element):
            return element.text
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            profiler = get_profiler()
            name = operation_name or func.__name__
            with profiler.profile(operation_type, name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class AdaptiveWaitOptimizer:
    """
    Optimizes wait times based on historical performance data.

    Learns from past page load times to reduce unnecessary waiting
    while maintaining reliability.
    """

    def __init__(
        self,
        min_wait_ms: float = 100,
        max_wait_ms: float = 30000,
        learning_rate: float = 0.1,
    ):
        """
        Initialize the adaptive wait optimizer.

        Args:
            min_wait_ms: Minimum wait time in milliseconds
            max_wait_ms: Maximum wait time in milliseconds
            learning_rate: Rate at which to adjust wait times (0-1)
        """
        self.min_wait_ms = min_wait_ms
        self.max_wait_ms = max_wait_ms
        self.learning_rate = learning_rate

        # Track wait times by operation
        self._wait_history: dict[str, list[float]] = defaultdict(list)
        self._optimal_waits: dict[str, float] = {}
        self._lock = threading.Lock()

    def get_optimal_wait(self, operation_id: str, default_ms: float = 5000) -> float:
        """
        Get the optimal wait time for an operation.

        Args:
            operation_id: Identifier for the operation
            default_ms: Default wait time if no history

        Returns:
            Optimal wait time in milliseconds
        """
        with self._lock:
            if operation_id in self._optimal_waits:
                return self._optimal_waits[operation_id]
            return min(max(default_ms, self.min_wait_ms), self.max_wait_ms)

    def record_actual_wait(
        self,
        operation_id: str,
        waited_ms: float,
        was_sufficient: bool,
    ) -> None:
        """
        Record the actual wait time and whether it was sufficient.

        Args:
            operation_id: Identifier for the operation
            waited_ms: How long we actually waited
            was_sufficient: Whether the wait was long enough
        """
        with self._lock:
            history = self._wait_history[operation_id]
            history.append(waited_ms)

            # Keep last 100 records
            if len(history) > 100:
                history.pop(0)

            # Calculate new optimal wait
            if len(history) >= 3:
                # Use 95th percentile of successful waits as baseline
                successful_waits = history[-20:]  # Recent history
                p95 = sorted(successful_waits)[int(len(successful_waits) * 0.95)]

                current_optimal = self._optimal_waits.get(operation_id, waited_ms)

                if was_sufficient:
                    # Can potentially reduce wait time
                    new_optimal = current_optimal - (current_optimal - p95) * self.learning_rate
                else:
                    # Need to increase wait time
                    new_optimal = current_optimal + (waited_ms * 0.5) * self.learning_rate

                # Clamp to bounds
                new_optimal = min(max(new_optimal, self.min_wait_ms), self.max_wait_ms)
                self._optimal_waits[operation_id] = new_optimal

    def get_stats(self) -> dict[str, Any]:
        """Get optimizer statistics."""
        with self._lock:
            return {
                "operations_tracked": len(self._wait_history),
                "optimal_waits": dict(self._optimal_waits),
                "history_sizes": {k: len(v) for k, v in self._wait_history.items()},
            }


class BatchOperationOptimizer:
    """
    Optimizes operations by batching similar requests.

    Groups element lookups and extractions to reduce round-trips.
    """

    def __init__(self, batch_size: int = 10, batch_timeout_ms: float = 100):
        """
        Initialize the batch optimizer.

        Args:
            batch_size: Maximum items per batch
            batch_timeout_ms: Max time to wait for batch to fill
        """
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self._pending_operations: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def create_batch_extraction_script(
        self,
        selectors: list[dict[str, str]],
    ) -> str:
        """
        Create a JavaScript script for batch element extraction.

        Args:
            selectors: List of selector definitions with name and selector

        Returns:
            JavaScript code for batch extraction
        """
        script_parts = ["var results = {};"]

        for item in selectors:
            name = item.get("name", "unknown")
            selector = item.get("selector", "")
            attribute = item.get("attribute", "text")

            # Escape selector for JavaScript
            escaped_selector = selector.replace("'", "\\'")

            if attribute == "text":
                script_parts.append(f"""
                    try {{
                        var el = document.querySelector('{escaped_selector}');
                        results['{name}'] = el ? el.textContent.trim() : null;
                    }} catch(e) {{
                        results['{name}'] = null;
                    }}
                """)
            else:
                script_parts.append(f"""
                    try {{
                        var el = document.querySelector('{escaped_selector}');
                        results['{name}'] = el ? el.getAttribute('{attribute}') : null;
                    }} catch(e) {{
                        results['{name}'] = null;
                    }}
                """)

        script_parts.append("return results;")
        return "\n".join(script_parts)

    def create_batch_multi_extraction_script(
        self,
        selectors: list[dict[str, str]],
    ) -> str:
        """
        Create a JavaScript script for extracting multiple elements.

        Args:
            selectors: List of selector definitions

        Returns:
            JavaScript code for batch multi-extraction
        """
        script_parts = ["var results = {};"]

        for item in selectors:
            name = item.get("name", "unknown")
            selector = item.get("selector", "")
            attribute = item.get("attribute", "text")

            escaped_selector = selector.replace("'", "\\'")

            if attribute == "text":
                script_parts.append(f"""
                    try {{
                        var els = document.querySelectorAll('{escaped_selector}');
                        results['{name}'] = Array.from(els).map(el => el.textContent.trim());
                    }} catch(e) {{
                        results['{name}'] = [];
                    }}
                """)
            else:
                script_parts.append(f"""
                    try {{
                        var els = document.querySelectorAll('{escaped_selector}');
                        results['{name}'] = Array.from(els).map(el => el.getAttribute('{attribute}'));
                    }} catch(e) {{
                        results['{name}'] = [];
                    }}
                """)

        script_parts.append("return results;")
        return "\n".join(script_parts)


def calculate_performance_score(report: PerformanceReport) -> dict[str, Any]:
    """
    Calculate an overall performance score based on the report.

    Args:
        report: Performance report to analyze

    Returns:
        Dictionary with score and breakdown
    """
    scores = {}
    weights = {}

    # SKU processing time score (0-100)
    if OperationType.TOTAL_SKU in report.operation_stats:
        sku_stats = report.operation_stats[OperationType.TOTAL_SKU]
        target = PerformanceProfiler.TARGET_SKU_TIME_MS
        if sku_stats.avg_ms <= target:
            scores["sku_time"] = 100
        elif sku_stats.avg_ms <= target * 2:
            scores["sku_time"] = int(100 - ((sku_stats.avg_ms - target) / target) * 50)
        else:
            scores["sku_time"] = int(max(0, 50 - ((sku_stats.avg_ms - target * 2) / target) * 25))
        weights["sku_time"] = 0.4

    # Navigation score
    if OperationType.NAVIGATION in report.operation_stats:
        nav_stats = report.operation_stats[OperationType.NAVIGATION]
        target = PerformanceProfiler.TARGET_NAVIGATION_MS
        if nav_stats.avg_ms <= target:
            scores["navigation"] = 100
        else:
            scores["navigation"] = int(max(0, 100 - ((nav_stats.avg_ms - target) / target) * 50))
        weights["navigation"] = 0.25

    # Wait efficiency score
    if OperationType.WAIT in report.operation_stats:
        wait_stats = report.operation_stats[OperationType.WAIT]
        wait_ratio = (
            wait_stats.total_ms / report.total_duration_ms if report.total_duration_ms > 0 else 0
        )
        # Penalize if waits take more than 30% of total time
        if wait_ratio <= 0.3:
            scores["wait_efficiency"] = 100
        else:
            scores["wait_efficiency"] = int(max(0, 100 - (wait_ratio - 0.3) * 200))
        weights["wait_efficiency"] = 0.2

    # Success rate score
    success_rates = [
        stats.success_rate for stats in report.operation_stats.values() if stats.count > 0
    ]
    if success_rates:
        avg_success_rate = sum(success_rates) / len(success_rates)
        scores["reliability"] = int(avg_success_rate * 100)
        weights["reliability"] = 0.15

    # Calculate weighted average
    if scores and weights:
        total_weight = sum(weights.get(k, 0) for k in scores)
        overall_score = (
            sum(scores[k] * weights.get(k, 0) for k in scores) / total_weight
            if total_weight > 0
            else 0
        )
    else:
        overall_score = 0

    return {
        "overall_score": round(overall_score, 1),
        "component_scores": {k: round(v, 1) for k, v in scores.items()},
        "weights": weights,
        "grade": _score_to_grade(overall_score),
    }


def _score_to_grade(score: float) -> str:
    """Convert a numeric score to a letter grade."""
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"
