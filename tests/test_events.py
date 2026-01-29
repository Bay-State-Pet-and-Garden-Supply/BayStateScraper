"""
Test Event Emitter System for Test Lab Real-Time Updates

Tests for the core event emitter system used by scraper runners.
Following TDD approach: RED - GREEN - REFACTOR
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


class TestBaseEvent:
    """Tests for the BaseEvent class."""

    def test_event_creation(self):
        """Test basic event creation."""
        from scrapers.events.base import BaseEvent

        event = BaseEvent(event_type="test.event", payload={"key": "value"})

        assert event.event_type == "test.event"
        assert event.payload == {"key": "value"}
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_event_serialization(self):
        """Test event serialization to dict."""
        from scrapers.events.base import BaseEvent

        event = BaseEvent(event_type="test.event", payload={"key": "value"})

        serialized = event.to_dict()

        assert serialized["event_type"] == "test.event"
        assert serialized["payload"] == {"key": "value"}
        assert "timestamp" in serialized

    def test_event_deserialization(self):
        """Test event deserialization from dict."""
        from scrapers.events.base import BaseEvent

        data = {"event_type": "test.event", "payload": {"key": "value"}, "timestamp": "2026-01-31T12:00:00Z"}

        event = BaseEvent.from_dict(data)

        assert event.event_type == "test.event"
        assert event.payload == {"key": "value"}


class TestSelectorValidationEvent:
    """Tests for SelectorValidationEvent."""

    def test_event_creation(self):
        """Test selector validation event creation."""
        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND")

        assert event.event_type == "test_lab.selector.validation"
        assert event.scraper == "amazon"
        assert event.sku == "B001234567"
        assert event.selector_name == "product_title"
        assert event.status == "FOUND"

    def test_event_status_values(self):
        """Test valid status values."""
        from scrapers.events.selector import SelectorValidationEvent

        for status in ["FOUND", "MISSING", "ERROR", "SKIPPED"]:
            event = SelectorValidationEvent(scraper="amazon", sku="B001234567", selector_name="test", selector_value=".test", status=status)
            assert event.status == status

    def test_event_serialization(self):
        """Test event serialization includes all fields."""
        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(
            scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND", duration_ms=150
        )

        serialized = event.to_dict()

        assert serialized["event_type"] == "test_lab.selector.validation"
        assert serialized["scraper"] == "amazon"
        assert serialized["sku"] == "B001234567"
        assert serialized["selector_name"] == "product_title"
        assert serialized["status"] == "FOUND"
        assert serialized["duration_ms"] == 150


class TestLoginStatusEvent:
    """Tests for LoginStatusEvent."""

    def test_event_creation(self):
        """Test login status event creation."""
        from scrapers.events.login import LoginStatusEvent

        event = LoginStatusEvent(scraper="amazon", sku="B001234567", status="SUCCESS")

        assert event.event_type == "test_lab.login.status"
        assert event.scraper == "amazon"
        assert event.sku == "B001234567"
        assert event.status == "SUCCESS"

    def test_event_with_selector_details(self):
        """Test login event with individual selector status."""
        from scrapers.events.login import LoginStatusEvent

        event = LoginStatusEvent(
            scraper="amazon",
            sku="B001234567",
            status="SUCCESS",
            username_field_status="FOUND",
            password_field_status="FOUND",
            submit_button_status="FOUND",
            success_indicator_status="FOUND",
        )

        assert event.username_field_status == "FOUND"
        assert event.password_field_status == "FOUND"
        assert event.submit_button_status == "FOUND"
        assert event.success_indicator_status == "FOUND"


class TestExtractionResultEvent:
    """Tests for ExtractionResultEvent."""

    def test_event_creation(self):
        """Test extraction result event creation."""
        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99")

        assert event.event_type == "test_lab.extraction.result"
        assert event.scraper == "amazon"
        assert event.sku == "B001234567"
        assert event.field_name == "price"
        assert event.status == "SUCCESS"
        assert event.field_value == "$99.99"

    def test_event_status_values(self):
        """Test valid extraction status values."""
        from scrapers.events.extraction import ExtractionResultEvent

        for status in ["SUCCESS", "EMPTY", "ERROR", "NOT_FOUND"]:
            event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="test", status=status)
            assert event.status == status


class TestEventEmitter:
    """Tests for EventEmitter class."""

    def test_emitter_subscribe(self):
        """Test event subscription."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()

        emitter.subscribe("test.event", callback)

        assert "test.event" in emitter._subscribers
        assert callback in emitter._subscribers["test.event"]

    def test_emitter_unsubscribe(self):
        """Test event unsubscription."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()

        emitter.subscribe("test.event", callback)
        emitter.unsubscribe("test.event", callback)

        assert callback not in emitter._subscribers.get("test.event", [])

    def test_emit_calls_subscribers(self):
        """Test that emit calls subscribed callbacks."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()

        from scrapers.events.base import BaseEvent

        event = BaseEvent(event_type="test.event", payload={"key": "value"})

        emitter.subscribe("test.event", callback)
        emitter.emit(event)

        callback.assert_called_once_with(event)

    def test_emit_multiple_subscribers(self):
        """Test that emit calls all subscribers."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback1 = MagicMock()
        callback2 = MagicMock()

        from scrapers.events.base import BaseEvent

        event = BaseEvent(event_type="test.event", payload={})

        emitter.subscribe("test.event", callback1)
        emitter.subscribe("test.event", callback2)
        emitter.emit(event)

        callback1.assert_called_once_with(event)
        callback2.assert_called_once_with(event)

    def test_emit_no_subscribers(self):
        """Test emit with no subscribers doesn't raise error."""
        from scrapers.events.emitter import EventEmitter
        from scrapers.events.base import BaseEvent

        emitter = EventEmitter()
        event = BaseEvent(event_type="test.event", payload={})

        # Should not raise
        emitter.emit(event)

    def test_wildcard_subscription(self):
        """Test wildcard subscription catches all events."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()

        from scrapers.events.base import BaseEvent

        event1 = BaseEvent(event_type="event.type1", payload={})
        event2 = BaseEvent(event_type="event.type2", payload={})

        emitter.subscribe("*", callback)
        emitter.emit(event1)
        emitter.emit(event2)

        assert callback.call_count == 2

    def test_login_selector_status(self):
        """Test login_selector_status convenience method."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()
        emitter.subscribe("test_lab.login.status", callback)

        emitter.login_selector_status(scraper="amazon", selector_name="username_field", status="FOUND")

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.scraper == "amazon"
        assert event.username_field_status == "FOUND"
        # Status is mapped to SUCCESS for FOUND
        assert event.status == "SUCCESS"

    def test_selector_validation(self):
        """Test selector_validation convenience method."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()
        emitter.subscribe("test_lab.selector.validation", callback)

        emitter.selector_validation(scraper="amazon", sku="B001234567", selector_name="price", selector_value=".price", status="FOUND")

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.scraper == "amazon"
        assert event.sku == "B001234567"
        assert event.selector_name == "price"
        assert event.status == "FOUND"

    def test_extraction_result(self):
        """Test extraction_result convenience method."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()
        callback = MagicMock()
        emitter.subscribe("test_lab.extraction.result", callback)

        emitter.extraction_result(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99")

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.scraper == "amazon"
        assert event.sku == "B001234567"
        assert event.field_name == "price"
        assert event.status == "SUCCESS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
