from __future__ import annotations

import argparse
import logging
import os
import sys
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ScraperSystem(Enum):
    LEGACY = "legacy"
    NEW = "new"


def setup_environment():
    """Setup Python path for imports."""
    if getattr(sys, "frozen", False):
        # Running in a PyInstaller bundle
        application_path = Path(sys.executable).parent
        project_root = application_path
        # Add the bundle path to Python path for imports
        if str(application_path) not in sys.path:
            sys.path.insert(0, str(application_path))
    else:
        # Running in development
        project_root = Path(__file__).parent.parent
        # Add the project root to the Python path
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))


# Setup environment before imports
setup_environment()

# Now we can import from backend
from scraper_backend.utils.logger import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="ProductScraper")
    parser.add_argument(
        "--run",
        type=str,
        help="Run a specific part of the application",
        choices=["scraper"],
    )
    parser.add_argument(
        "--file", type=str, help="Path to the Excel file to be processed by the scraper"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode for scrapers (sets HEADLESS=False and DEBUG_MODE=True)",
    )
    args = parser.parse_args()

    # Set debug environment variables if --debug is used
    if args.debug:
        os.environ["HEADLESS"] = "False"
        os.environ["DEBUG_MODE"] = "True"

    # Initialize logging
    setup_logging(debug_mode=args.debug)

    if args.run == "scraper":
        from scraper_backend.core.settings_manager import settings

        # Check which scraper system to use
        scraper_system_str = settings.get("scraper_system", "new")
        try:
            scraper_system = ScraperSystem(scraper_system_str)
        except ValueError:
            logger.error(f"Invalid scraper_system: {scraper_system_str}")
            return

        if scraper_system == ScraperSystem.LEGACY:
            logger.info("Using legacy archived scraper system...")
            from scraper_backend.scrapers.main import run_scraping
        else:
            logger.info("Using new modular scraper system...")
            from scraper_backend.scrapers.main import run_scraping

        if args.file:
            run_scraping(args.file)
        else:
            logger.error("Please provide a file path using the --file argument.")
    else:
        # If no arguments, print help
        parser.print_help()


if __name__ == "__main__":
    main()
