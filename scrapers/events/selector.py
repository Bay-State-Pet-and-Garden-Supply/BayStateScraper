"""
Selector Validation Event

Event emitted when a selector is validated during test runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class SelectorValidationEvent:
    """Event for selector validation results."""

    event_type: str = "test_lab.selector.validation"

    VALID_STATUSES = frozenset(["FOUND", "MISSING", "ERROR", "SKIPPED"])

    def __init__(
        self,
        scraper: str,
        sku: str,
        selector_name: str,
        selector_value: str,
        status: str,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {self.VALID_STATUSES}")

        self.scraper = scraper
        self.sku = sku
        self.selector_name = selector_name
        self.selector_value = selector_value
        self.status = status
        self.duration_ms = duration_ms
        self.error_message = error_message
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat() + "Z",
            "scraper": self.scraper,
            "sku": self.sku,
            "selector_name": self.selector_name,
            "selector_value": self.selector_value,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectorValidationEvent":
        """Deserialize event from dictionary."""
        return cls(
            scraper=data["scraper"],
            sku=data["sku"],
            selector_name=data["selector_name"],
            selector_value=data["selector_value"],
            status=data["status"],
            duration_ms=data.get("duration_ms"),
            error_message=data.get("error_message"),
        )

    def __repr__(self) -> str:
        return f"SelectorValidationEvent(scraper={self.scraper}, selector={self.selector_name}, status={self.status})"
