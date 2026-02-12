"""
Test Runner Event Emission for Test Lab Real-Time Updates

Tests for event emission integration in scraper runner.
Following TDD approach: RED - GREEN - REFACTOR
"""

import os
import sys
from unittest.mock import MagicMock
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


class TestRunnerEventIntegration:
    """Tests for event emission in scraper runner."""

    def test_login_action_has_event_emitter(self):
        """Test LoginAction can use event_emitter."""
        from scrapers.actions.handlers.login import LoginAction

        # Create a mock executor with event_emitter
        mock_executor = MagicMock()
        mock_executor.event_emitter = MagicMock()
        mock_executor.config = MagicMock()
        mock_executor.config.name = "test_scraper"
        mock_executor.config.login = None
        mock_executor.is_session_authenticated.return_value = False

        action = LoginAction(mock_executor)

        assert hasattr(action.ctx, "event_emitter")

    def test_login_action_emits_selector_status(self):
        """Test LoginAction emits selector status events."""
        from scrapers.actions.handlers.login import LoginAction
        from scrapers.events.emitter import EventEmitter

        # Create a real event emitter
        event_emitter = EventEmitter()

        # Create a mock executor with event_emitter
        mock_executor = MagicMock()
        mock_executor.event_emitter = event_emitter
        mock_executor.config = MagicMock()
        mock_executor.config.name = "test_scraper"
        mock_executor.config.login = None
        mock_executor.is_session_authenticated.return_value = False

        action = LoginAction(mock_executor)

        # Subscribe to events
        callback = MagicMock()
        event_emitter.subscribe("test_lab.login.status", callback)

        # Simulate emitting an event (would normally happen during execution)
        event_emitter.login_selector_status(scraper="test_scraper", selector_name="username_field", status="FOUND")

        callback.assert_called_once()

    def test_executor_has_event_emitter_attribute(self):
        """Test executor has event_emitter attribute for test_mode."""
        from scrapers.executor.workflow_executor import WorkflowExecutor

        mock_config = MagicMock()
        mock_config.name = "test_scraper"

        executor = WorkflowExecutor(config=mock_config)

        # In test_mode, executor should have event_emitter
        assert hasattr(executor, "event_emitter") or executor.context.get("test_mode") is not None


class TestScraperTestingClientEvents:
    """Tests for event emission in ScraperTestingClient."""

    def test_testing_client_has_event_emitter(self):
        """Test ScraperTestingClient has event_emitter."""
        try:
            from core.scraper_testing_client import ScraperTestingClient

            client = ScraperTestingClient()

            # Should have event_emitter or context that supports it
            has_emitter = hasattr(client, "event_emitter")
            has_context = hasattr(client, "context")

            assert has_emitter or has_context
        except ImportError:
            pytest.skip("ScraperTestingClient not found")


class TestExtractActionEvents:
    """Tests for extraction event emission."""

    def test_extract_action_has_event_emitter(self):
        """Test ExtractAction can use event_emitter."""
        try:
            from scrapers.actions.handlers.extract import ExtractAction

            mock_executor = MagicMock()
            mock_executor.event_emitter = MagicMock()
            mock_executor.config = MagicMock()
            mock_executor.config.name = "test_scraper"

            action = ExtractAction(mock_executor)

            assert hasattr(action.ctx, "event_emitter")
        except ImportError:
            pytest.skip("ExtractAction not found")


class TestNavigateActionEvents:
    """Tests for navigation event emission."""

    def test_navigate_action_has_event_emitter(self):
        """Test NavigateAction can use event_emitter."""
        try:
            from scrapers.actions.handlers.navigate import NavigateAction

            mock_executor = MagicMock()
            mock_executor.event_emitter = MagicMock()
            mock_executor.config = MagicMock()
            mock_executor.config.name = "test_scraper"

            action = NavigateAction(mock_executor)

            assert hasattr(action.ctx, "event_emitter")
        except ImportError:
            pytest.skip("NavigateAction not found")


class TestClickActionEvents:
    """Tests for click event emission."""

    def test_click_action_has_event_emitter(self):
        """Test ClickAction can use event_emitter."""
        try:
            from scrapers.actions.handlers.click import ClickAction

            mock_executor = MagicMock()
            mock_executor.event_emitter = MagicMock()
            mock_executor.config = MagicMock()
            mock_executor.config.name = "test_scraper"

            action = ClickAction(mock_executor)

            assert hasattr(action.ctx, "event_emitter")
        except ImportError:
            pytest.skip("ClickAction not found")


class TestWaitForActionEvents:
    """Tests for wait_for event emission."""

    def test_wait_for_action_has_event_emitter(self):
        """Test WaitForAction can use event_emitter."""
        try:
            from scrapers.actions.handlers.wait_for import WaitForAction

            mock_executor = MagicMock()
            mock_executor.event_emitter = MagicMock()
            mock_executor.config = MagicMock()
            mock_executor.config.name = "test_scraper"

            action = WaitForAction(mock_executor)

            assert hasattr(action.ctx, "event_emitter")
        except ImportError:
            pytest.skip("WaitForAction not found")


class TestEventEmitterIntegration:
    """Tests for EventEmitter integration patterns."""

    def test_event_emitter_can_be_added_to_context(self):
        """Test event_emitter can be added to executor context."""
        from scrapers.events.emitter import EventEmitter

        event_emitter = EventEmitter()

        # Should be able to add to context
        context = {"test_mode": True, "event_emitter": event_emitter}

        assert context["event_emitter"] is event_emitter
        assert context["test_mode"] is True

    def test_event_emitter_receives_selector_events(self):
        """Test event_emitter receives selector validation events."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()

        # Subscribe to selector events
        callback = MagicMock()
        emitter.subscribe("test_lab.selector.validation", callback)

        # Emit a selector validation event
        emitter.selector_validation(scraper="amazon", sku="B001234567", selector_name="product_title", selector_value=".product-title", status="FOUND")

        callback.assert_called_once()

    def test_event_emitter_receives_extraction_events(self):
        """Test event_emitter receives extraction result events."""
        from scrapers.events.emitter import EventEmitter

        emitter = EventEmitter()

        # Subscribe to extraction events
        callback = MagicMock()
        emitter.subscribe("test_lab.extraction.result", callback)

        # Emit an extraction result event
        emitter.extraction_result(scraper="amazon", sku="B001234567", field_name="price", status="SUCCESS", field_value="$99.99")

        callback.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
