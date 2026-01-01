import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Define project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_logging(debug_mode: bool = False):
    """Configure centralized logging to file and console."""
    log_level = logging.DEBUG if debug_mode else logging.INFO

    # Create logs directory if it doesn't exist
    log_dir = Path(PROJECT_ROOT) / "logs"
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "app.log"

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # Formatters
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")

    # File Handler (Rotating: 10MB max, 5 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logging.info(f"Logging initialized. Level: {logging.getLevelName(log_level)}")
