import json
import logging
import sys
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import pytest
from core.api_client import ScraperAPIClient
from utils.api_handler import ScraperAPIHandler
from utils.logger import JSONFormatter, setup_logging, reset_logging


class TestJSONFormatter:
    """Tests for the JSONFormatter class."""

    def test_format_basic_log(self):
        """Test basic log formatting."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_formatter")
        logger.setLevel(logging.INFO)

        # Create a handler with our formatter
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Capture output
        import io

        stream = io.StringIO()
        handler.stream = stream

        logger.info("Test message")

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_formatter"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    def test_format_with_context(self):
        """Test log formatting with context fields."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_context")
        logger.setLevel(logging.INFO)

        # Create a handler with our formatter
        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        logger.info("Processing SKU", extra={"job_id": "job-123", "sku": "ABC", "scraper_name": "test"})

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["job_id"] == "job-123"
        assert parsed["sku"] == "ABC"
        assert parsed["scraper_name"] == "test"

    def test_format_error_with_exception(self):
        """Test log formatting with exception info."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_error")
        logger.setLevel(logging.ERROR)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.error("An error occurred", exc_info=True)

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["level"] == "ERROR"
        assert parsed["error_type"] == "ValueError"
        assert parsed["error_message"] == "Test error"


class TestScraperAPIHandler:
    """Tests for the ScraperAPIHandler class."""

    def test_emit_adds_to_buffer(self):
        """Test that emit adds logs to the buffer."""
        mock_client = MagicMock()
        mock_client.post_logs = AsyncMock()

        handler = ScraperAPIHandler(
            mock_client,
            job_id="test-job",
            buffer_size=10,
            flush_interval=60.0,
            max_retries=1,
        )

        logger = logging.getLogger("test_buffer")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Test message 1")
        logger.info("Test message 2")

        # Check buffer BEFORE shipping thread can flush
        # The shipping thread waits 60 seconds, so buffer should still have entries
        assert len(handler._buffer) == 2
        assert handler._buffer[0]["message"] == "Test message 1"
        assert handler._buffer[1]["message"] == "Test message 2"

        # Verify that API would be called with these logs on flush
        handler.flush()
        time.sleep(0.1)  # Wait for async flush

        # Verify post_logs was called with the buffered entries
        mock_client.post_logs.assert_called_once()
        args = mock_client.post_logs.call_args[0]
        assert args[0] == "test-job"
        assert len(args[1]) == 2
        assert args[1][0]["message"] == "Test message 1"
        assert args[1][1]["message"] == "Test message 2"

        handler.close()

    def test_context_fields_included(self):
        """Test that context fields are included in API logs."""
        mock_client = MagicMock()
        mock_client.post_logs = AsyncMock()

        handler = ScraperAPIHandler(
            mock_client,
            job_id="test-job",
            buffer_size=10,
            flush_interval=60.0,
            max_retries=1,
        )

        logger = logging.getLogger("test_context_api")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info(
            "Processing item",
            extra={"job_id": "job-456", "scraper_name": "amazon", "sku": "XYZ123", "step": "extract"},
        )

        # Check buffer BEFORE shipping thread can flush
        assert len(handler._buffer) == 1
        entry = handler._buffer[0]
        assert entry["job_id"] == "job-456"
        assert entry["scraper_name"] == "amazon"
        assert entry["sku"] == "XYZ123"
        assert entry["step"] == "extract"

        # Verify API receives context fields
        handler.flush()
        time.sleep(0.1)

        mock_client.post_logs.assert_called_once()
        args = mock_client.post_logs.call_args[0]
        assert args[1][0]["job_id"] == "job-456"
        assert args[1][0]["scraper_name"] == "amazon"

        handler.close()

    def test_flush_on_close(self):
        """Test that close() flushes remaining logs."""
        mock_client = MagicMock()
        mock_client.post_logs = AsyncMock()

        handler = ScraperAPIHandler(
            mock_client,
            job_id="test-job",
            buffer_size=100,  # Large buffer so automatic flush won't trigger
            flush_interval=60.0,
            max_retries=1,
        )

        logger = logging.getLogger("test_close")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("Message before close")

        # Buffer should have entry
        assert len(handler._buffer) == 1

        # Close should trigger shipping
        handler.close()

        # Wait for shipping thread
        time.sleep(0.5)

        # post_logs should have been called
        mock_client.post_logs.assert_called_once()
        args = mock_client.post_logs.call_args[0]
        assert args[0] == "test-job"
        assert len(args[1]) == 1
        assert args[1][0]["message"] == "Message before close"

    def test_no_infinite_recursion(self):
        """Test that API logging doesn't cause infinite recursion."""
        mock_client = MagicMock()
        mock_client.post_logs = AsyncMock()

        handler = ScraperAPIHandler(
            mock_client,
            job_id="test-job",
            buffer_size=10,
            flush_interval=60.0,
            max_retries=1,
        )

        logger = logging.getLogger("httpx")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        # This should not cause infinite recursion
        logger.debug("HTTP request")

        time.sleep(0.1)
        # If we get here without stack overflow, test passed
        handler.close()


class TestSetupLogging:
    """Tests for the setup_logging function."""

    def test_setup_logging_idempotent(self):
        """Test that calling setup_logging multiple times doesn't duplicate handlers."""
        reset_logging()

        logger1 = logging.getLogger("test_idempotent1")
        logger1.setLevel(logging.DEBUG)

        setup_logging(debug_mode=False)
        setup_logging(debug_mode=False)
        setup_logging(debug_mode=False)

        root = logging.getLogger()
        handler_count = len(root.handlers)

        # Should have at most 2 handlers (console + optional file)
        # Not 6 handlers from 3 calls
        assert handler_count <= 2, f"Expected <= 2 handlers, got {handler_count}"

    def test_json_output_by_default(self):
        """Test that JSON output is the default."""
        reset_logging()

        import io

        setup_logging(debug_mode=False)

        # Capture output from the root logger's handler (which uses JSONFormatter)
        root = logging.getLogger()

        # Find the stream handler that was added by setup_logging
        stream_handler = None
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and hasattr(handler, "stream"):
                if hasattr(handler.formatter, "__class__") and handler.formatter.__class__.__name__ == "JSONFormatter":
                    stream_handler = handler
                    break

        assert stream_handler is not None, "JSONFormatter handler not found"

        # Capture output using a custom stream
        captured = io.StringIO()
        old_stream = stream_handler.stream
        try:
            stream_handler.stream = captured

            logger = logging.getLogger("test_json")
            logger.handlers = []  # Clear existing handlers
            logger.setLevel(logging.INFO)
            logger.addHandler(stream_handler)  # Use the JSON handler

            logger.info("Test message")

            output = captured.getvalue()
        finally:
            stream_handler.stream = old_stream  # Restore original stream

        # Should be valid JSON - take the last line (the actual test message)
        lines = output.strip().split("\n")
        last_line = lines[-1]
        parsed = json.loads(last_line)
        assert parsed["message"] == "Test message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
