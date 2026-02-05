"""
Integration Tests for Test Lab Real-Time Updates

End-to-end integration tests for the complete Test Lab event flow.
Following TDD approach: RED - GREEN - REFACTOR
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


class TestEventFlowIntegration:
    """Tests for complete event flow from emitter to handlers."""

    def test_full_event_flow(self):
        """Test complete event flow: emitter -> handler -> database."""
        from scrapers.events.emitter import EventEmitter
        from scrapers.events.handlers.selector import SelectorResultHandler

        # Create emitter and handler
        emitter = EventEmitter()
        mock_supabase = MagicMock()
        handler = SelectorResultHandler(mock_supabase)

        # Subscribe handler to events
        emitter.subscribe("test_lab.selector.validation", handler.handle)

        # Emit event
        emitter.selector_validation(scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND")

        # Verify handler was called
        mock_supabase.table.assert_called_once_with("scraper_selector_results")
        mock_supabase.table.return_value.insert.assert_called_once()

    def test_database_persistence(self):
        """Test that events are persisted to database correctly."""
        from scrapers.events.emitter import EventEmitter
        from scrapers.events.handlers.login import LoginResultHandler

        emitter = EventEmitter()
        mock_supabase = MagicMock()
        handler = LoginResultHandler(mock_supabase)

        emitter.subscribe("test_lab.login.status", handler.handle)

        emitter.login_selector_status(scraper="amazon", selector_name="username_field", status="FOUND")

        # Verify the correct data was sent to database
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["scraper"] == "amazon"
        assert call_args["overall_status"] == "SUCCESS"  # FOUND maps to SUCCESS


class TestWebSocketIntegration:
    """Tests for WebSocket server integration."""

    def test_server_with_emitter(self):
        """Test WebSocket server receives events from emitter."""
        from scrapers.events.websocket_server import TestLabWebSocketServer
        from scrapers.events.emitter import EventEmitter

        # Create server and mock socket
        server = TestLabWebSocketServer()
        mock_socket = MagicMock()
        connection = server.connect(mock_socket)

        # Subscribe to test room
        server.subscribe(connection.client_id, "test-123")

        # Broadcast event
        server.broadcast_to_room("test-123", {"event_type": "test_lab.selector.validation", "data": {"scraper": "amazon", "status": "FOUND"}})

        # Verify socket received broadcast
        mock_socket.emit.assert_called()

    def test_multiple_clients_receive_events(self):
        """Test that multiple clients in same room receive events."""
        from scrapers.events.websocket_server import TestLabWebSocketServer

        server = TestLabWebSocketServer()
        mock_socket1 = MagicMock()
        mock_socket2 = MagicMock()

        connection1 = server.connect(mock_socket1)
        connection2 = server.connect(mock_socket2)

        # Both subscribe to same room
        server.subscribe(connection1.client_id, "test-456")
        server.subscribe(connection2.client_id, "test-456")

        # Broadcast
        server.broadcast_to_room("test-456", {"event_type": "test"})

        # Both should receive
        assert mock_socket1.emit.call_count == 1
        assert mock_socket2.emit.call_count == 1


class TestGracefulDegradation:
    """Tests for graceful degradation when WebSocket unavailable."""

    def test_fallback_to_polling(self):
        """Test that system can fall back to polling when WebSocket unavailable."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()

        # Subscribe with callback
        callback = MagicMock()
        emitter.subscribe("test_lab.selector.validation", callback)

        # Emit event
        emitter.selector_validation(scraper="amazon", sku="B001234567", selector_name="test", selector_value=".test", status="FOUND")

        # Callback should be called even without WebSocket
        callback.assert_called_once()


class TestEndToEndEventTypes:
    """Tests for all event types in the system."""

    def test_selector_event_flow(self):
        """Test selector validation event flow."""
        from scrapers.events.selector import SelectorValidationEvent
        from scrapers.events.emitter import EventEmitter

        event = SelectorValidationEvent(scraper="amazon", sku="B001234567", selector_name="price", selector_value=".price", status="FOUND")

        assert event.event_type == "test_lab.selector.validation"
        assert event.scraper == "amazon"
        assert event.status == "FOUND"

    def test_login_event_flow(self):
        """Test login status event flow."""
        from scrapers.events.login import LoginStatusEvent

        event = LoginStatusEvent(scraper="amazon", sku="B001234567", status="SUCCESS", username_field_status="FOUND", password_field_status="FOUND")

        assert event.event_type == "test_lab.login.status"
        assert event.status == "SUCCESS"

    def test_extraction_event_flow(self):
        """Test extraction result event flow."""
        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99")

        assert event.event_type == "test_lab.extraction.result"
        assert event.field_name == "price"
        assert event.status == "SUCCESS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
