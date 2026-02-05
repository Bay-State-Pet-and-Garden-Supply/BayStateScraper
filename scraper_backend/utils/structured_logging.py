"""
Structured logging utilities for BayStateScraper.

Provides:
- JSONFormatter: Formats logs as JSON for log aggregation
- SensitiveDataFilter: Redacts sensitive data from log records
- generate_trace_id: Generates unique trace IDs for request tracking
- setup_structured_logging: Configures structured logging for the application
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from datetime import datetime
from logging import LogRecord
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that redacts sensitive data from log records.

    Sensitive patterns include:
    - API keys (bsr_*, X-API-Key headers)
    - Passwords
    - Tokens
    - Authorization headers
    """

    # Patterns that match sensitive data
    SENSITIVE_PATTERNS = [
        (r"bsr_[a-zA-Z0-9]{32,}", "[API_KEY_REDACTED]"),
        (r'X-API-Key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_-]+', "[API_KEY_REDACTED]"),
        (r"Bearer\s+[a-zA-Z0-9_\-\.]+", "[TOKEN_REDACTED]"),
        (r'["\']?password["\']?\s*[:=]\s*["\']?[^\s"\']+', "[PASSWORD_REDACTED]"),
        (r'Authorization["\']?\s*[:=]\s*["\']?[^\s"\']+', "[AUTH_REDACTED]"),
    ]

    def filter(self, record: LogRecord) -> bool:
        """Redact sensitive data from log message and extra fields."""
        # Redact from message
        record.msg = self._redact(str(record.msg))

        # Redact from args (formatted message arguments)
        if record.args:
            record.args = tuple(self._redact(str(arg)) if isinstance(arg, (str, bytes)) else arg for arg in record.args)

        # Redact from extra fields that will be included in JSON
        if hasattr(record, "job_id") and record.job_id:
            record.job_id = self._redact(str(record.job_id)) if record.job_id else None
        if hasattr(record, "scraper_name") and record.scraper_name:
            record.scraper_name = self._redact(str(record.scraper_name)) if record.scraper_name else None
        if hasattr(record, "trace_id") and record.trace_id:
            record.trace_id = self._redact(str(record.trace_id)) if record.trace_id else None

        return True

    def _redact(self, text: str) -> str:
        """Apply all redaction patterns to text."""
        result = text
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured log output.

    Outputs logs as JSON objects with consistent fields:
    - timestamp: ISO format timestamp
    - level: Log level (INFO, ERROR, etc.)
    - logger: Logger name
    - message: Log message
    - job_id: Job context (if available)
    - scraper_name: Scraper context (if available)
    - trace_id: Trace ID for debugging (if available)
    - module: Module name
    - function: Function name
    - line: Line number
    """

    def format(self, record: LogRecord) -> str:
        """Format log record as JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context fields if present
        if hasattr(record, "job_id") and record.job_id:
            log_data["job_id"] = record.job_id
        if hasattr(record, "scraper_name") and record.scraper_name:
            log_data["scraper_name"] = record.scraper_name
        if hasattr(record, "trace_id") and record.trace_id:
            log_data["trace_id"] = record.trace_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "message",
                "job_id",
                "scraper_name",
                "trace_id",
            ):
                try:
                    # Only include JSON-serializable values
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    pass

        return json.dumps(log_data)


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    return str(uuid.uuid4())[:8]


def setup_structured_logging(debug: bool = False) -> None:
    """
    Configure structured logging with JSON output and sensitive data redaction.

    Args:
        debug: Enable debug logging level
    """
    log_level = logging.DEBUG if debug else logging.INFO

    # Create JSON formatter
    json_formatter = JSONFormatter()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(json_formatter)
    handler.addFilter(SensitiveDataFilter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Also configure our module logger
    module_logger = logging.getLogger(__name__)
    module_logger.setLevel(log_level)


if __name__ == "__main__":
    # Demo usage
    setup_structging(debug=False)
    logger = logging.getLogger(__name__)
    logger.info("Test message", extra={"job_id": "test-job", "trace_id": generate_trace_id()})
