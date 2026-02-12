from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Setup path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows encoding issues by forcing UTF-8 for stdout/stderr
if sys.platform == "win32":
    import io

    # Detach and wrap stdout/stderr with UTF-8 encoding
    # 'errors="replace"' ensures that if encoding fails, it doesn't crash the script
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Setup logging to stream to stdout so parent process can capture it
from utils.logger import setup_logging

setup_logging(debug_mode=False, json_output=True)
logger = logging.getLogger(__name__)

from scrapers.runtime import run_scraping


def main():
    parser = argparse.ArgumentParser(description="Run Scraper Job")
    parser.add_argument("--skus", nargs="*", help="List of SKUs to scrape")
    parser.add_argument("--scrapers", nargs="*", help="List of scraper names to run")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode")
    parser.add_argument("--max-workers", type=int, default=3, help="Max workers")

    args = parser.parse_args()

    logger.info(f"Starting job with SKUs: {args.skus}, Scrapers: {args.scrapers}, Test Mode: {args.test_mode}")

    try:
        run_scraping(
            skus=args.skus,
            selected_sites=args.scrapers,
            test_mode=args.test_mode,
            max_workers=args.max_workers,
        )
        logger.info("Configuration completed successfully")
    except Exception as e:
        logger.error(f"Job failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
