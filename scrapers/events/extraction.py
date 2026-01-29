"""
Extraction Result Event

Event emitted when field extraction completes during test runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ExtractionResultEvent:
    """Event for field extraction results."""

    event_type: str = "test_lab.extraction.result"

    VALID_STATUSES = frozenset(["SUCCESS", "EMPTY", "ERROR", "NOT_FOUND"])

    def __init__(
        self,
        scraper: str,
        sku: str,
        field_name: str,
        status: str,
        field_value: str | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {self.VALID_STATUSES}")

        self.scraper = scraper
        self.sku = sku
        self.field_name = field_name
        self.status = status
        self.field_value = field_value
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
            "field_name": self.field_name,
            "status": self.status,
            "field_value": self.field_value,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionResultEvent":
        """Deserialize event from dictionary."""
        return cls(
            scraper=data["scraper"],
            sku=data["sku"],
            field_name=data["field_name"],
            status=data["status"],
            field_value=data.get("field_value"),
            duration_ms=data.get("duration_ms"),
            error_message=data.get("error_message"),
        )

    def __repr__(self) -> str:
        return f"ExtractionResultEvent(scraper={self.scraper}, field={self.field_name}, status={self.status})"
