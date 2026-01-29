"""
Login Status Event

Event emitted when login validation completes during test runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class LoginStatusEvent:
    """Event for login validation results."""

    event_type: str = "test_lab.login.status"

    VALID_STATUSES = frozenset(["SUCCESS", "FAILED", "SKIPPED", "ERROR"])

    def __init__(
        self,
        scraper: str,
        sku: str,
        status: str,
        username_field_status: str | None = None,
        password_field_status: str | None = None,
        submit_button_status: str | None = None,
        success_indicator_status: str | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {self.VALID_STATUSES}")

        self.scraper = scraper
        self.sku = sku
        self.status = status
        self.username_field_status = username_field_status
        self.password_field_status = password_field_status
        self.submit_button_status = submit_button_status
        self.success_indicator_status = success_indicator_status
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
            "status": self.status,
            "username_field_status": self.username_field_status,
            "password_field_status": self.password_field_status,
            "submit_button_status": self.submit_button_status,
            "success_indicator_status": self.success_indicator_status,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoginStatusEvent":
        """Deserialize event from dictionary."""
        return cls(
            scraper=data["scraper"],
            sku=data["sku"],
            status=data["status"],
            username_field_status=data.get("username_field_status"),
            password_field_status=data.get("password_field_status"),
            submit_button_status=data.get("submit_button_status"),
            success_indicator_status=data.get("success_indicator_status"),
            duration_ms=data.get("duration_ms"),
            error_message=data.get("error_message"),
        )

    def __repr__(self) -> str:
        return f"LoginStatusEvent(scraper={self.scraper}, status={self.status})"
