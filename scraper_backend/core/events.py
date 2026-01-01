"""
Structured Event System for Scraper Observability

This module provides a type-safe, structured event bus that replaces the fragile
"Log-as-API" pattern. Events are JSON-serializable, typed, and can be persisted.

Key Design Principles:
1. Events are first-class data structures, not log strings
2. Every event has a type, timestamp, and job context
3. Events are immutable after creation
4. The system supports both real-time consumption and persistence
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Event Types
# =============================================================================


class EventType(str, Enum):
    """Enumeration of all structured event types.

    Grouped by category:
    - JOB_*: Job lifecycle events
    - SCRAPER_*: Per-scraper events
    - SKU_*: Per-SKU processing events
    - PROGRESS_*: Progress tracking events
    - SYSTEM_*: System-level events
    """

    # Job Lifecycle
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_CANCELLED = "job.cancelled"

    # Scraper Lifecycle
    SCRAPER_STARTED = "scraper.started"
    SCRAPER_COMPLETED = "scraper.completed"
    SCRAPER_FAILED = "scraper.failed"
    SCRAPER_BROWSER_INIT = "scraper.browser_init"
    SCRAPER_BROWSER_RESTART = "scraper.browser_restart"

    # SKU Processing
    SKU_PROCESSING = "sku.processing"
    SKU_SUCCESS = "sku.success"
    SKU_NOT_FOUND = "sku.not_found"
    SKU_FAILED = "sku.failed"
    SKU_NO_RESULTS = "sku.no_results"

    # Progress Updates (structured replacement for PROGRESS: lines)
    PROGRESS_UPDATE = "progress.update"
    PROGRESS_WORKER = "progress.worker"

    # Selector Results (for test mode debugging)
    SELECTOR_FOUND = "selector.found"
    SELECTOR_MISSING = "selector.missing"

    # System Events
    SYSTEM_WARNING = "system.warning"
    SYSTEM_ERROR = "system.error"
    SYSTEM_INFO = "system.info"

    # Data Sync
    DATA_SYNCED = "data.synced"
    DATA_SYNC_FAILED = "data.sync_failed"

    # Login Status
    LOGIN_SELECTOR_STATUS = "login.selector_status"


class EventSeverity(str, Enum):
    """Severity levels for events (analogous to log levels)."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =============================================================================
# Event Data Classes
# =============================================================================


@dataclass(frozen=True)
class ScraperEvent:
    """A structured, immutable event from the scraper system.

    All events have:
    - event_type: The type of event (from EventType enum)
    - timestamp: When the event occurred (ISO format)
    - job_id: The job this event belongs to (for correlation)
    - event_id: Unique identifier for this event
    - severity: The severity level of the event

    Plus optional context-specific fields in the `data` dict.
    """

    event_type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    job_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    severity: EventSeverity = EventSeverity.INFO
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to JSON-serializable dictionary."""
        result = {
            "event_type": self.event_type.value
            if isinstance(self.event_type, EventType)
            else self.event_type,
            "timestamp": self.timestamp,
            "job_id": self.job_id,
            "event_id": self.event_id,
            "severity": self.severity.value
            if isinstance(self.severity, EventSeverity)
            else self.severity,
            "data": self.data,
        }
        return result

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScraperEvent:
        """Create event from dictionary."""
        return cls(
            event_type=EventType(d["event_type"]),
            timestamp=d.get("timestamp", datetime.now().isoformat()),
            job_id=d.get("job_id"),
            event_id=d.get("event_id", str(uuid.uuid4())[:8]),
            severity=EventSeverity(d.get("severity", "info")),
            data=d.get("data", {}),
        )

    def __str__(self) -> str:
        """Human-readable representation for logging compatibility."""
        parts = [f"[{self.event_type.value}]"]
        if self.job_id:
            parts.append(f"job={self.job_id}")
        if self.data:
            for key, value in self.data.items():
                if value is not None:
                    parts.append(f"{key}={value}")
        return " ".join(parts)


# =============================================================================
# Event Bus (Thread-safe event management)
# =============================================================================


EventCallback = Callable[[ScraperEvent], None]


class EventBus:
    """Thread-safe event bus for publishing and subscribing to events.

    Features:
    - Multiple subscribers (for UI, persistence, logging)
    - Event buffering (keeps last N events per job)
    - Thread-safe event emission
    - Optional event persistence to JSON file
    """

    def __init__(
        self, buffer_size: int = 500, persist_path: Path | None = None, max_jobs: int = 100
    ):
        self._subscribers: list[EventCallback] = []
        self._events: list[ScraperEvent] = []
        self._buffer_size = buffer_size
        self._max_jobs = max_jobs
        self._lock = threading.Lock()
        self._persist_path = persist_path

        # Per-job event tracking
        self._job_events: dict[str, list[ScraperEvent]] = {}
        # Order of job IDs for cleanup
        self._job_order: list[str] = []

    def subscribe(self, callback: EventCallback) -> None:
        """Register a callback to receive events."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        """Remove a callback from receiving events."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def emit(self, event: ScraperEvent) -> None:
        """Emit an event to all subscribers.

        Thread-safe. Events are buffered and optionally persisted.
        """
        with self._lock:
            # Add to global buffer
            self._events.append(event)
            if len(self._events) > self._buffer_size:
                self._events = self._events[-self._buffer_size :]

            # Add to per-job buffer
            if event.job_id:
                if event.job_id not in self._job_events:
                    # Maintain max jobs limit
                    if len(self._job_order) >= self._max_jobs:
                        oldest_job = self._job_order.pop(0)
                        self._job_events.pop(oldest_job, None)

                    self._job_events[event.job_id] = []
                    self._job_order.append(event.job_id)
                else:
                    # Move to end of order (LRU behavior)
                    if self._job_order[-1] != event.job_id:
                        self._job_order.remove(event.job_id)
                        self._job_order.append(event.job_id)

                self._job_events[event.job_id].append(event)
                # Limit per-job buffer
                if len(self._job_events[event.job_id]) > self._buffer_size:
                    self._job_events[event.job_id] = self._job_events[event.job_id][
                        -self._buffer_size :
                    ]

            # Notify subscribers
            for callback in self._subscribers:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Event subscriber error: {e}")

            # Persist if configured
            if self._persist_path:
                self._persist_event(event)

    def get_events(
        self,
        job_id: str | None = None,
        event_types: list[EventType] | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[ScraperEvent]:
        """Retrieve buffered events with optional filtering.

        Args:
            job_id: Filter to specific job
            event_types: Filter to specific event types
            since: ISO timestamp to filter events after
            limit: Maximum number of events to return
        """
        with self._lock:
            if job_id and job_id in self._job_events:
                events = self._job_events[job_id].copy()
            else:
                events = self._events.copy()

        # Apply filters
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        if since:
            events = [e for e in events if e.timestamp > since]

        return events[-limit:]

    def get_events_as_dicts(
        self,
        job_id: str | None = None,
        event_types: list[EventType] | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve buffered events as dictionaries (for JSON serialization)."""
        events = self.get_events(job_id, event_types, since, limit)
        return [e.to_dict() for e in events]

    def clear_job(self, job_id: str) -> None:
        """Clear events for a specific job."""
        with self._lock:
            if job_id in self._job_events:
                del self._job_events[job_id]

    def _persist_event(self, event: ScraperEvent) -> None:
        """Persist event to JSON file (append mode)."""
        if not self._persist_path:
            return

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to persist event: {e}")


# =============================================================================
# Event Emitter (Factory for creating events with job context)
# =============================================================================


class EventEmitter:
    """Factory for creating and emitting events with consistent job context.

    Use this class within a scraper job to emit events. It maintains the job_id
    context so you don't have to pass it every time.
    """

    def __init__(self, event_bus: EventBus, job_id: str):
        self._bus = event_bus
        self._job_id = job_id
        self._start_time = time.time()

    @property
    def job_id(self) -> str:
        return self._job_id

    def _emit(
        self,
        event_type: EventType,
        severity: EventSeverity = EventSeverity.INFO,
        **data: Any,
    ) -> ScraperEvent:
        """Internal method to create and emit an event."""
        event = ScraperEvent(
            event_type=event_type,
            job_id=self._job_id,
            severity=severity,
            data=data,
        )
        self._bus.emit(event)
        return event

    # Job lifecycle events
    def job_started(
        self,
        total_skus: int,
        scrapers: list[str],
        max_workers: int = 1,
        test_mode: bool = False,
    ) -> ScraperEvent:
        return self._emit(
            EventType.JOB_STARTED,
            total_skus=total_skus,
            scrapers=scrapers,
            max_workers=max_workers,
            test_mode=test_mode,
        )

    def job_completed(
        self,
        successful: int,
        failed: int,
        duration_seconds: float,
    ) -> ScraperEvent:
        return self._emit(
            EventType.JOB_COMPLETED,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration_seconds, 2),
            success_rate=round(successful / (successful + failed) * 100, 1)
            if (successful + failed) > 0
            else 0,
        )

    def job_failed(self, error: str) -> ScraperEvent:
        return self._emit(
            EventType.JOB_FAILED,
            severity=EventSeverity.ERROR,
            error=error,
        )

    def job_cancelled(self, reason: str = "User requested") -> ScraperEvent:
        return self._emit(
            EventType.JOB_CANCELLED,
            severity=EventSeverity.WARNING,
            reason=reason,
        )

    # Scraper lifecycle events
    def scraper_started(
        self,
        scraper: str,
        worker_id: str,
        total_skus: int,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SCRAPER_STARTED,
            scraper=scraper,
            worker_id=worker_id,
            total_skus=total_skus,
        )

    def scraper_completed(
        self,
        scraper: str,
        worker_id: str,
        processed: int,
        successful: int,
        failed: int,
        duration_seconds: float,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SCRAPER_COMPLETED,
            scraper=scraper,
            worker_id=worker_id,
            processed=processed,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration_seconds, 2),
        )

    def scraper_failed(
        self,
        scraper: str,
        worker_id: str,
        error: str,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SCRAPER_FAILED,
            severity=EventSeverity.ERROR,
            scraper=scraper,
            worker_id=worker_id,
            error=error,
        )

    def browser_init(
        self,
        scraper: str,
        worker_id: str,
        duration_seconds: float,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SCRAPER_BROWSER_INIT,
            scraper=scraper,
            worker_id=worker_id,
            duration_seconds=round(duration_seconds, 2),
        )

    def browser_restart(
        self,
        scraper: str,
        worker_id: str,
        reason: str = "batch limit",
    ) -> ScraperEvent:
        return self._emit(
            EventType.SCRAPER_BROWSER_RESTART,
            scraper=scraper,
            worker_id=worker_id,
            reason=reason,
        )

    # SKU processing events
    def sku_processing(self, scraper: str, worker_id: str, sku: str) -> ScraperEvent:
        return self._emit(
            EventType.SKU_PROCESSING,
            scraper=scraper,
            worker_id=worker_id,
            sku=sku,
        )

    def sku_success(
        self,
        scraper: str,
        worker_id: str,
        sku: str,
        data: dict[str, Any] | None = None,
        duration_seconds: float | None = None,
        sku_type: str = "test",
        is_passing: bool = True,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SKU_SUCCESS,
            scraper=scraper,
            worker_id=worker_id,
            sku=sku,
            sku_type=sku_type,
            is_passing=is_passing,
            extracted_data=data or {},
            duration_seconds=round(duration_seconds, 2) if duration_seconds else None,
        )

    def sku_not_found(
        self,
        scraper: str,
        worker_id: str,
        sku: str,
        sku_type: str = "test",
        is_passing: bool = False,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SKU_NOT_FOUND,
            scraper=scraper,
            worker_id=worker_id,
            sku=sku,
            sku_type=sku_type,
            is_passing=is_passing,
        )

    def sku_failed(
        self,
        scraper: str,
        worker_id: str,
        sku: str,
        error: str,
        sku_type: str = "test",
        is_passing: bool = False,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SKU_FAILED,
            severity=EventSeverity.ERROR,
            scraper=scraper,
            worker_id=worker_id,
            sku=sku,
            sku_type=sku_type,
            is_passing=is_passing,
            error=error,
        )

    def sku_no_results(
        self,
        scraper: str,
        worker_id: str,
        sku: str,
        sku_type: str = "test",
        is_passing: bool = False,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SKU_NO_RESULTS,
            scraper=scraper,
            worker_id=worker_id,
            sku=sku,
            sku_type=sku_type,
            is_passing=is_passing,
        )

    # Progress events (the main replacement for PROGRESS: log lines)
    def progress_update(
        self,
        scraper: str,
        current: int,
        total: int,
        percentage: int,
        skus_processed: int,
    ) -> ScraperEvent:
        return self._emit(
            EventType.PROGRESS_UPDATE,
            scraper=scraper,
            current=current,
            total=total,
            percentage=percentage,
            skus_processed=skus_processed,
        )

    def worker_progress(
        self,
        scraper: str,
        worker_id: str,
        status: str,
        completed: int = 0,
        failed: int = 0,
        current_item: str | None = None,
    ) -> ScraperEvent:
        return self._emit(
            EventType.PROGRESS_WORKER,
            scraper=scraper,
            worker_id=worker_id,
            status=status,
            completed=completed,
            failed=failed,
            current_item=current_item,
        )

    # Selector events (for test mode debugging)
    def selector_found(
        self,
        scraper: str,
        sku: str,
        selector_name: str,
        value: str,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SELECTOR_FOUND,
            scraper=scraper,
            sku=sku,
            selector_name=selector_name,
            value=value[:100] if value else None,  # Truncate long values
        )

    def selector_missing(
        self,
        scraper: str,
        sku: str,
        selector_name: str,
    ) -> ScraperEvent:
        return self._emit(
            EventType.SELECTOR_MISSING,
            severity=EventSeverity.WARNING,
            scraper=scraper,
            sku=sku,
            selector_name=selector_name,
        )

    # Data sync events
    def data_synced(
        self,
        sku: str,
        scraper: str,
        data: dict[str, Any],
    ) -> ScraperEvent:
        return self._emit(
            EventType.DATA_SYNCED,
            sku=sku,
            scraper=scraper,
            synced_data=data,
        )

    def data_sync_failed(
        self,
        sku: str,
        scraper: str,
        error: str,
    ) -> ScraperEvent:
        return self._emit(
            EventType.DATA_SYNC_FAILED,
            severity=EventSeverity.ERROR,
            sku=sku,
            scraper=scraper,
            error=error,
        )

    # Login events
    def login_selector_status(
        self, scraper: str, selector_name: str, status: str
    ) -> ScraperEvent:
        return self._emit(
            EventType.LOGIN_SELECTOR_STATUS,
            scraper=scraper,
            selector_name=selector_name,
            status=status,
        )

    # System events (for backwards compatibility with log messages)
    def info(self, message: str, **data: Any) -> ScraperEvent:
        return self._emit(EventType.SYSTEM_INFO, message=message, **data)

    def warning(self, message: str, **data: Any) -> ScraperEvent:
        return self._emit(
            EventType.SYSTEM_WARNING,
            severity=EventSeverity.WARNING,
            message=message,
            **data,
        )

    def error(self, message: str, **data: Any) -> ScraperEvent:
        return self._emit(
            EventType.SYSTEM_ERROR,
            severity=EventSeverity.ERROR,
            message=message,
            **data,
        )


# =============================================================================
# Global Event Bus Instance
# =============================================================================

# Default persistence path in data/events/
_default_persist_path = Path(__file__).parent.parent.parent / "data" / "events" / "events.jsonl"

# Global event bus - accessible across the application
event_bus = EventBus(buffer_size=1000, persist_path=_default_persist_path)


def create_emitter(job_id: str) -> EventEmitter:
    """Create an EventEmitter for a specific job.

    Usage:
        emitter = create_emitter("job_20241219_143000")
        emitter.job_started(total_skus=100, scrapers=["bradley", "amazon"])
        emitter.progress_update(scraper="bradley", current=10, total=100, percentage=10, skus_processed=5)
        emitter.sku_success(scraper="bradley", worker_id="W1", sku="123456", data={"name": "Product"})
    """
    return EventEmitter(event_bus, job_id)


# =============================================================================
# Logging Bridge (backwards compatibility)
# =============================================================================


class LoggingEventSubscriber:
    """Subscriber that logs events to the standard Python logging system.

    This provides backwards compatibility - events are still visible in logs.
    """

    def __init__(self, logger_name: str = "scraper.events"):
        self._logger = logging.getLogger(logger_name)

    def __call__(self, event: ScraperEvent) -> None:
        """Handle event by logging it."""
        level = {
            EventSeverity.DEBUG: logging.DEBUG,
            EventSeverity.INFO: logging.INFO,
            EventSeverity.WARNING: logging.WARNING,
            EventSeverity.ERROR: logging.ERROR,
            EventSeverity.CRITICAL: logging.CRITICAL,
        }.get(event.severity, logging.INFO)

        self._logger.log(level, str(event))


# Auto-register logging subscriber for backwards compatibility
_logging_subscriber = LoggingEventSubscriber()
event_bus.subscribe(_logging_subscriber)
