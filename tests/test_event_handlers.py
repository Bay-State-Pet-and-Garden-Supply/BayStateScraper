"""
Test Event Handlers for Test Lab Real-Time Updates

Tests for event handlers that persist Test Lab events to database.
Following TDD approach: RED - GREEN - REFACTOR
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


class TestSelectorResultHandler:
    """Tests for SelectorResultHandler."""

    def test_handler_persists_selector_event(self):
        """Test handler persists selector validation event to database."""
        from scrapers.events.handlers.selector import SelectorResultHandler

        # Mock Supabase client
        mock_supabase = MagicMock()

        handler = SelectorResultHandler(mock_supabase)

        # Create a mock event
        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(
            scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND", duration_ms=150
        )

        # Call handle
        handler.handle(event)

        # Verify insert was called
        mock_supabase.table.assert_called_once_with("scraper_selector_results")
        mock_supabase.table.return_value.insert.assert_called_once()

    def test_handler_persists_missing_selector(self):
        """Test handler persists MISSING selector status."""
        from scrapers.events.handlers.selector import SelectorResultHandler

        mock_supabase = MagicMock()
        handler = SelectorResultHandler(mock_supabase)

        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(scraper="amazon", sku="B001234567", selector_name="price", selector_value=".price", status="MISSING")

        handler.handle(event)

        mock_supabase.table.return_value.insert.assert_called_once()
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["status"] == "MISSING"
        assert call_args["scraper"] == "amazon"

    def test_handler_persists_error_selector(self):
        """Test handler persists ERROR selector status."""
        from scrapers.events.handlers.selector import SelectorResultHandler

        mock_supabase = MagicMock()
        handler = SelectorResultHandler(mock_supabase)

        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(
            scraper="amazon",
            sku="B001234567",
            selector_name="add_to_cart",
            selector_value="#add-to-cart",
            status="ERROR",
            error_message="Element not interactable",
        )

        handler.handle(event)

        mock_supabase.table.return_value.insert.assert_called_once()
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["status"] == "ERROR"
        assert call_args["error_message"] == "Element not interactable"


class TestLoginResultHandler:
    """Tests for LoginResultHandler."""

    def test_handler_persists_login_event(self):
        """Test handler persists login status event to database."""
        from scrapers.events.handlers.login import LoginResultHandler

        mock_supabase = MagicMock()
        handler = LoginResultHandler(mock_supabase)

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

        handler.handle(event)

        mock_supabase.table.assert_called_once_with("scraper_login_results")
        mock_supabase.table.return_value.insert.assert_called_once()

    def test_handler_persists_failed_login(self):
        """Test handler persists failed login status."""
        from scrapers.events.handlers.login import LoginResultHandler

        mock_supabase = MagicMock()
        handler = LoginResultHandler(mock_supabase)

        from scrapers.events.login import LoginStatusEvent

        event = LoginStatusEvent(
            scraper="amazon",
            sku="B001234567",
            status="FAILED",
            username_field_status="FOUND",
            password_field_status="FOUND",
            submit_button_status="MISSING",
            error_message="Submit button not found",
        )

        handler.handle(event)

        mock_supabase.table.return_value.insert.assert_called_once()
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["overall_status"] == "FAILED"
        assert call_args["submit_button_status"] == "MISSING"


class TestExtractionResultHandler:
    """Tests for ExtractionResultHandler."""

    def test_handler_persists_extraction_event(self):
        """Test handler persists extraction result event to database."""
        from scrapers.events.handlers.extraction import ExtractionResultHandler

        mock_supabase = MagicMock()
        handler = ExtractionResultHandler(mock_supabase)

        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99", duration_ms=250)

        handler.handle(event)

        mock_supabase.table.assert_called_once_with("scraper_extraction_results")
        mock_supabase.table.return_value.insert.assert_called_once()

    def test_handler_persists_empty_extraction(self):
        """Test handler persists EMPTY extraction status."""
        from scrapers.events.handlers.extraction import ExtractionResultHandler

        mock_supabase = MagicMock()
        handler = ExtractionResultHandler(mock_supabase)

        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="brand", status="EMPTY")

        handler.handle(event)

        mock_supabase.table.return_value.insert.assert_called_once()
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["status"] == "EMPTY"
        assert call_args["field_name"] == "brand"

    def test_handler_persists_not_found_extraction(self):
        """Test handler persists NOT_FOUND extraction status."""
        from scrapers.events.handlers.extraction import ExtractionResultHandler

        mock_supabase = MagicMock()
        handler = ExtractionResultHandler(mock_supabase)

        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="rating", status="NOT_FOUND", error_message="Selector returned no results")

        handler.handle(event)

        mock_supabase.table.return_value.insert.assert_called_once()
        call_args = mock_supabase.table.return_value.insert.call_args[0][0]
        assert call_args["status"] == "NOT_FOUND"


class TestConsoleLoggerHandler:
    """Tests for ConsoleLoggerHandler."""

    def test_handler_logs_selector_event(self):
        """Test handler logs selector validation events to console."""
        from scrapers.events.handlers.console import ConsoleLoggerHandler

        handler = ConsoleLoggerHandler()

        from scrapers.events.selector import SelectorValidationEvent

        event = SelectorValidationEvent(scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND")

        # Should not raise
        handler.handle(event)

    def test_handler_logs_login_event(self):
        """Test handler logs login status events to console."""
        from scrapers.events.handlers.console import ConsoleLoggerHandler

        handler = ConsoleLoggerHandler()

        from scrapers.events.login import LoginStatusEvent

        event = LoginStatusEvent(scraper="amazon", sku="B001234567", status="SUCCESS")

        # Should not raise
        handler.handle(event)

    def test_handler_logs_extraction_event(self):
        """Test handler logs extraction result events to console."""
        from scrapers.events.handlers.console import ConsoleLoggerHandler

        handler = ConsoleLoggerHandler()

        from scrapers.events.extraction import ExtractionResultEvent

        event = ExtractionResultEvent(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99")

        # Should not raise
        handler.handle(event)


class TestHandlerRegistration:
    """Tests for handler registration and discovery."""

    def test_handler_module_init_exports_handlers(self):
        """Test that handlers module exports all handlers."""
        from scrapers.events import handlers

        assert hasattr(handlers, "SelectorResultHandler")
        assert hasattr(handlers, "LoginResultHandler")
        assert hasattr(handlers, "ExtractionResultHandler")
        assert hasattr(handlers, "ConsoleLoggerHandler")

    def test_selector_handler_is_class(self):
        """Test SelectorResultHandler is a class."""
        from scrapers.events.handlers.selector import SelectorResultHandler

        assert isinstance(SelectorResultHandler, type)

    def test_login_handler_is_class(self):
        """Test LoginResultHandler is a class."""
        from scrapers.events.handlers.login import LoginResultHandler

        assert isinstance(LoginResultHandler, type)

    def test_extraction_handler_is_class(self):
        """Test ExtractionResultHandler is a class."""
        from scrapers.events.handlers.extraction import ExtractionResultHandler

        assert isinstance(ExtractionResultHandler, type)

    def test_console_handler_is_class(self):
        """Test ConsoleLoggerHandler is a class."""
        from scrapers.events.handlers.console import ConsoleLoggerHandler

        assert isinstance(ConsoleLoggerHandler, type)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
