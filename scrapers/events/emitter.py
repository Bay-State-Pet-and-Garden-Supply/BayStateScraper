"""
Event Emitter

Core event emitter for Test Lab real-time updates.
Provides publish-subscribe pattern for event handling.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, Union

from .selector import SelectorValidationEvent
from .login import LoginStatusEvent
from .extraction import ExtractionResultEvent


class TestLabEvent(Protocol):
    """Protocol for Test Lab events."""

    event_type: str
    timestamp: Any
    to_dict: Callable[[], dict[str, Any]]


class EventEmitter:
    """Event emitter for Test Lab events."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[TestLabEvent], None]]] = {}

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[TestLabEvent], None],
    ) -> None:
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[TestLabEvent], None],
    ) -> None:
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def emit(self, event: TestLabEvent) -> None:
        """Emit an event to all subscribers."""
        # Notify specific event type subscribers
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception:
                    # Don't let subscriber errors prevent other callbacks
                    pass

        # Notify wildcard subscribers
        if "*" in self._subscribers:
            for callback in self._subscribers["*"]:
                try:
                    callback(event)
                except Exception:
                    pass

    def login_selector_status(
        self,
        scraper: str,
        selector_name: str,
        status: str,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Convenience method to emit login selector status."""
        # Map selector status to login status
        if status == "FOUND":
            login_status = "SUCCESS"
        elif status == "MISSING":
            login_status = "FAILED"
        elif status == "SKIPPED":
            login_status = "SKIPPED"
        else:
            login_status = "ERROR"

        event = LoginStatusEvent(
            scraper=scraper,
            sku="",  # Login events may not have a specific SKU
            status=login_status,
            username_field_status=status if selector_name == "username_field" else None,
            password_field_status=status if selector_name == "password_field" else None,
            submit_button_status=status if selector_name == "submit_button" else None,
            success_indicator_status=status if selector_name == "success_indicator" else None,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        self.emit(event)

    def selector_validation(
        self,
        scraper: str,
        sku: str,
        selector_name: str,
        selector_value: str,
        status: str,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Convenience method to emit selector validation event."""
        event = SelectorValidationEvent(
            scraper=scraper,
            sku=sku,
            selector_name=selector_name,
            selector_value=selector_value,
            status=status,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        self.emit(event)

    def extraction_result(
        self,
        scraper: str,
        sku: str,
        field_name: str,
        status: str,
        field_value: str | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Convenience method to emit extraction result event."""
        event = ExtractionResultEvent(
            scraper=scraper,
            sku=sku,
            field_name=field_name,
            status=status,
            field_value=field_value,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        self.emit(event)
