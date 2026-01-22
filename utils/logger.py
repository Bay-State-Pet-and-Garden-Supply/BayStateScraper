from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# Define project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Track if logging has been configured to avoid duplicate setup
_logging_configured = False


class JSONFormatter(logging.Formatter):
    """JSON formatter that outputs log records as JSON lines conforming to LOG_SCHEMA.md."""

    def __init__(self, *, include_context: bool = True):
        super().__init__()
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add optional fields from record if present
        optional_fields = ["job_id", "runner_name", "scraper_name", "sku", "step", "worker_id"]
        for field in optional_fields:
            value = getattr(record, field, None)
            if value is not None and value != "":
                log_data[field] = value

        # Add error fields if present
        if record.exc_info:
            log_data["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            log_data["error_message"] = str(record.exc_info[1]) if record.exc_info[1] else None
            # Stack trace is intentionally not included by default (can be large)

        # Add duration_ms if present
        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms

        return json.dumps(log_data)


def _get_log_level() -> int:
    """Determine log level from environment or default."""
    env_level = os.environ.get("LOG_LEVEL", "").upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return getattr(logging, env_level)
    return logging.INFO


def _get_log_format() -> str:
    """Determine log format from environment (default: json)."""
    env_format = os.environ.get("LOG_FORMAT", "json").lower()
    if env_format == "pretty":
        return "pretty"
    return "json"  # Default to JSON


class NoHttpFilter(logging.Filter):
    """Filter to suppress httpx/httpcore noise from API client logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.name.startswith("httpx") or record.name.startswith("httpcore") or record.name.startswith("urllib3"))


def setup_logging(
    debug_mode: bool = False,
    *,
    json_output: bool = True,
    use_file_handler: bool = True,
) -> None:
    """Configure centralized logging for BayStateScraper.

    Args:
        debug_mode: If True, set log level to DEBUG.
        json_output: If True, emit JSON to stdout (default, Docker-friendly).
        use_file_handler: If True, also write rotating logs to file.
    """
    global _logging_configured

    # Idempotent: skip if already configured
    if _logging_configured and not debug_mode:
        return

    # Determine log level
    if debug_mode:
        log_level = logging.DEBUG
    else:
        log_level = _get_log_level()

    # Determine format
    log_format = _get_log_format()
    use_pretty = log_format == "pretty"

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear existing handlers to avoid duplicates (unless already configured)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create formatter
    if json_output and not use_pretty:
        json_formatter = JSONFormatter()
        # Console handler outputs JSON
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(json_formatter)
        console_handler.addFilter(NoHttpFilter())
        logger.addHandler(console_handler)
    else:
        # Pretty output for local development
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(NoHttpFilter())
        logger.addHandler(console_handler)

    # Optional: File handler for persistent logs
    if use_file_handler:
        log_dir = Path(PROJECT_ROOT) / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "app.log"

        # File handler always uses JSON for consistency
        file_formatter = JSONFormatter()
        file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    _logging_configured = True

    # Log initialization (avoid recursion by using root logger directly)
    root_logger = logging.getLogger()
    level_name = logging.getLevelName(log_level)
    if use_pretty:
        root_logger.info(f"Logging initialized (pretty mode). Level: {level_name}")
    else:
        root_logger.info(f"Logging initialized (JSON mode). Level: {level_name}")


def reset_logging() -> None:
    """Reset logging configuration (useful for testing)."""
    global _logging_configured
    _logging_configured = False

    logger = logging.getLogger()
    if logger.hasHandlers():
        logger.handlers.clear()
