"""
Base Event Class

Foundation for all Test Lab events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class BaseEvent:
    """Base class for all Test Lab events."""

    def __init__(
        self,
        event_type: str = "base.event",
        payload: dict[str, str] | None = None,
    ) -> None:
        self.event_type = event_type
        self.timestamp = datetime.utcnow()
        self.payload = payload or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat() + "Z",
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BaseEvent":
        """Deserialize event from dictionary."""
        event_type = data.get("event_type", "base.event")
        payload = data.get("payload")
        event = cls(event_type=event_type, payload=payload)
        if "timestamp" in data:
            event.timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        return event

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(event_type={self.event_type}, timestamp={self.timestamp.isoformat()})"
