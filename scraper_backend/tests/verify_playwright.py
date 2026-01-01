import logging
import os
import sys
import time

# Ensure project root is in path
current_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/tests
src_dir = os.path.dirname(current_dir)  # .../src
project_root = os.path.dirname(src_dir)  # .../ProductScraper
sys.path.insert(0, project_root)

from scraper_backend.core.settings_manager import settings
from scraper_backend.scrapers.exceptions import ScraperError
from scraper_backend.scrapers.executor.workflow_executor import WorkflowExecutor
from scraper_backend.scrapers.models.config import ScraperConfig, SelectorConfig, WorkflowStep

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_playwright")


def verify_playwright():
    logger.info("Starting Playwright Verification...")

    # Force settings
    settings.set("browser_backend", "playwright")
    settings.set("selenium_timeout", 30)

    # Create a dummy configuration - only pass required fields
    config = ScraperConfig(
        name="test_scraper",
        base_url="https://example.com",
        selectors=[
            SelectorConfig(name="page_title", selector="h1"),
            SelectorConfig(name="paragraph", selector="p"),
        ],
        workflows=[
            WorkflowStep(action="navigate", params={"url": "https://example.com"}),
            WorkflowStep(action="wait_for", params={"selector": "h1"}),
            WorkflowStep(
                action="extract_single", params={"field": "title", "selector": "page_title"}
            ),
            WorkflowStep(
                action="extract_multiple", params={"field": "text_content", "selector": "paragraph"}
            ),
        ],
    )

    executor = WorkflowExecutor(config, headless=True)

    try:
        # Check if backend is correct
        backend_name = type(executor.browser).__name__
        logger.info(f"Initialized Browser Backend: {backend_name}")

        if "Playwright" not in backend_name:
            logger.error("Failed to initialize Playwright backend!")
            return False

        # Execute
        logger.info("Executing workflow...")
        result = executor.execute_workflow()

        logger.info("Workflow Results:")
        logger.info(result.get("results"))

        # Verify Extraction
        title = result.get("results", {}).get("title")
        if title == "Example Domain":
            logger.info("Extraction verification successful: Title matched")
        else:
            logger.error(
                f"Extraction verification failed: Expected 'Example Domain', got '{title}'"
            )
            return False

        logger.info("Playwright verification passed!")
        return True

    except Exception as e:
        logger.error(f"Verification failed with error: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        if executor.browser:
            if hasattr(executor.browser, "quit"):
                executor.browser.quit()
            elif hasattr(executor.browser, "close"):  # Playwright native
                executor.browser.close()


if __name__ == "__main__":
    verify_playwright()
