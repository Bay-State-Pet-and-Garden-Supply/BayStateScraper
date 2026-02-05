"""
Tests for structured logging functionality.

Tests the structured logging implementation including:
- JSON output format
- Context fields (job_id, scraper_name, trace_id)
- Sensitive data redaction
- Trace ID generation
"""

import json
import logging
import sys
import os
import re

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from scraper_backend.utils.structured_logging import (
    SensitiveDataFilter,
    JSONFormatter,
    generate_trace_id,
    setup_structured_logging,
)


class TestSensitiveDataFilter:
    """Tests for the SensitiveDataFilter class."""

    def test_redacts_api_key_pattern(self):
        """Test that API key patterns are redacted."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key: bsr_abc123def456ghi789jkl012mno345pqr",
            args=(),
            exc_info=None,
        )

        filter_instance = SensitiveDataFilter()
        filter_instance.filter(record)

        assert "[API_KEY_REDACTED]" in record.msg
        assert "bsr_" not in record.msg

    def test_redacts_password_pattern(self):
        """Test that password patterns are redacted."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Login failed: password=secret123",
            args=(),
            exc_info=None,
        )

        filter_instance = SensitiveDataFilter()
        filter_instance.filter(record)

        assert "[PASSWORD_REDACTED]" in record.msg
        assert "secret123" not in record.msg

    def test_redacts_bearer_token(self):
        """Test that Bearer token patterns are redacted."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token sent: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            args=(),
            exc_info=None,
        )

        filter_instance = SensitiveDataFilter()
        filter_instance.filter(record)

        assert "[TOKEN_REDACTED]" in record.msg
        assert "eyJ" not in record.msg

    def test_redacts_authorization_header(self):
        """Test that Authorization header patterns are redacted."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Request headers: Authorization=Basic dXNlcjpwYXNz",
            args=(),
            exc_info=None,
        )

        filter_instance = SensitiveDataFilter()
        filter_instance.filter(record)

        assert "[AUTH_REDACTED]" in record.msg
        assert "Basic" not in record.msg


class TestJSONFormatter:
    """Tests for the JSONFormatter class."""

    def test_format_basic_log(self):
        """Test basic log formatting as JSON."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_json_basic")
        logger.setLevel(logging.INFO)

        # Capture output
        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        logger.info("Test message")

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_json_basic"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    def test_format_with_context_fields(self):
        """Test log formatting with context fields."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_json_context")
        logger.setLevel(logging.INFO)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        logger.info(
            "Processing SKU",
            extra={
                "job_id": "job-123",
                "scraper_name": "amazon",
                "trace_id": "abc12345",
                "sku": "TEST-SKU",
            },
        )

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["job_id"] == "job-123"
        assert parsed["scraper_name"] == "amazon"
        assert parsed["trace_id"] == "abc12345"
        assert parsed["sku"] == "TEST-SKU"

    def test_format_error_with_exception(self):
        """Test log formatting with exception info."""
        formatter = JSONFormatter()
        logger = logging.getLogger("test_json_error")
        logger.setLevel(logging.ERROR)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        try:
            raise ValueError("Test error message")
        except ValueError:
            logger.error("An error occurred", exc_info=True)

        output = stream.getvalue()
        parsed = json.loads(output.strip())

        assert parsed["level"] == "ERROR"
        assert parsed["exception"] is not None
        assert "ValueError" in parsed["exception"]


class TestGenerateTraceId:
    """Tests for the generate_trace_id function."""

    def test_generates_unique_ids(self):
        """Test that trace IDs are unique."""
        ids = [generate_trace_id() for _ in range(100)]
        unique_ids = set(ids)

        # Should have 100 unique IDs
        assert len(unique_ids) == 100

    def test_generates_short_ids(self):
        """Test that trace IDs are short (8 characters)."""
        trace_id = generate_trace_id()
        assert len(trace_id) == 8

    def test_generates_hex_characters(self):
        """Test that trace IDs use hex characters."""
        trace_id = generate_trace_id()
        # Should only contain hex characters (0-9, a-f)
        assert all(c in "0123456789abcdef" for c in trace_id)


class TestSetupStructuredLogging:
    """Tests for the setup_structured_logging function."""

    def test_sets_json_formatter(self):
        """Test that setup_structured_logging configures JSON output."""
        # Reset logging
        root = logging.getLogger()
        root.handlers.clear()

        setup_structured_logging(debug=False)

        # Check that at least one handler has JSONFormatter
        has_json_formatter = False
        for handler in root.handlers:
            if isinstance(handler.formatter, JSONFormatter):
                has_json_formatter = True
                break

        assert has_json_formatter, "JSONFormatter should be configured"

    def test_sets_sensitive_data_filter(self):
        """Test that setup_structured_logging adds sensitive data filter."""
        # Reset logging
        root = logging.getLogger()
        root.handlers.clear()

        setup_structured_logging(debug=False)

        # Check that at least one handler has SensitiveDataFilter
        has_filter = False
        for handler in root.handlers:
            for f in handler.filters:
                if isinstance(f, SensitiveDataFilter):
                    has_filter = True
                    break

        assert has_filter, "SensitiveDataFilter should be configured"

    def test_debug_mode_sets_debug_level(self):
        """Test that debug=True sets log level to DEBUG."""
        # Reset logging
        root = logging.getLogger()
        root.handlers.clear()

        setup_structured_logging(debug=True)

        assert root.level == logging.DEBUG


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
