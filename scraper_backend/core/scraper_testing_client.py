"""
Scraper Testing Client
Provides interface for local scraper testing only.
"""

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TestingMode(Enum):
    """Testing mode enumeration."""

    LOCAL = "local"


class ScraperTestingError(Exception):
    """Base exception for scraper testing errors."""

    pass


class ScraperTestingAuthError(ScraperTestingError):
    """Authentication error."""

    pass


class ScraperTestingTimeoutError(ScraperTestingError):
    """Timeout error."""

    pass


class ScraperTestingJobError(ScraperTestingError):
    """Job execution error."""

    pass


class ScraperTestingClient:
    """
    Local scraper testing client.
    Provides interface for local scraper testing only.
    """

    def __init__(self, mode: TestingMode = TestingMode.LOCAL, headless: bool = True, **kwargs):
        """
        Initialize the testing client.

        Args:
            mode: Testing mode (only LOCAL supported)
            headless: Whether to run browser in headless mode
            **kwargs: Additional arguments (ignored)
        """
        if mode != TestingMode.LOCAL:
            raise ValueError("Only LOCAL testing mode is supported")

        self.mode = mode
        self.headless = headless

    async def __aenter__(self):
        """Enter async context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context."""
        pass

    async def run_scraper(self, scraper_name: str, skus: list[str], **kwargs) -> dict[str, Any]:
        """
        Run a scraper locally with the specified SKUs.

        Args:
            scraper_name: Name of the scraper to run
            skus: List of SKUs to scrape
            **kwargs: Additional arguments

        Returns:
            Dict with run results
        """
        return await self._run_local_scraper(scraper_name, skus, **kwargs)

    async def _run_local_scraper(
        self, scraper_name: str, skus: list[str], **kwargs
    ) -> dict[str, Any]:
        """
        Run scraper locally.
        """
        import asyncio

        return await asyncio.to_thread(self._run_local_scraper_sync, scraper_name, skus, **kwargs)

    def _run_local_scraper_sync(
        self, scraper_name: str, skus: list[str], **kwargs
    ) -> dict[str, Any]:
        """
        Synchronous implementation of local scraper run.
        """
        import os
        import time

        from scraper_backend.scrapers.executor.workflow_executor import WorkflowExecutor
        from scraper_backend.scrapers.parser.yaml_parser import ScraperConfigParser

        start_time = time.time()
        products = []
        errors = []
        overall_success = True

        try:
            # Load configuration
            parser = ScraperConfigParser()
            config = None

            # 1. Try Supabase first
            try:
                from scraper_backend.core.database.supabase_sync import supabase_sync

                if supabase_sync.initialize():
                    config_dict = supabase_sync.get_scraper(scraper_name)
                    if config_dict:
                        config = parser.load_from_dict(config_dict)
                        logger.info(f"Loaded config from Supabase for test: {scraper_name}")
            except Exception as e:
                logger.warning(f"Failed to load config from Supabase: {e}")

            # 2. Fallback to local file
            if not config:
                # assume project root relative to this file
                project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )

                # Check multiple possible locations for local configs
                config_paths = [
                    os.path.join(
                        project_root, "scraper_backend/scrapers/config", f"{scraper_name}.yaml"
                    ),
                    os.path.join(project_root, "src/scrapers/configs", f"{scraper_name}.yaml"),
                ]

                for path in config_paths:
                    if os.path.exists(path):
                        config = parser.load_from_file(path)
                        logger.info(f"Loaded config from local file for test: {path}")
                        break

            if not config:
                raise FileNotFoundError(
                    f"Config for {scraper_name} not found in Supabase or locally"
                )

            # Initialize executor
            executor = WorkflowExecutor(config, headless=self.headless)

            try:
                for sku in skus:
                    try:
                        # Use execute_workflow API (returns dict)
                        result = executor.execute_workflow(context={"sku": sku}, quit_browser=False)

                        if result.get("success"):
                            if result.get("no_results_found"):
                                # Track no results as a valid outcome but no product data
                                # But we MUST include the no_results_found flag in the products list
                                # for tests to verify it.
                                products.append({"SKU": sku, "no_results_found": True})
                            else:
                                # Add product data
                                extracted_data = result.get("results", {})
                                if extracted_data:
                                    # Ensure SKU is in the data
                                    data = extracted_data.copy()
                                    if "SKU" not in data:
                                        data["SKU"] = sku
                                    products.append(data)
                        else:
                            overall_success = False
                            error_msg = result.get("error", "Unknown error")
                            errors.append(f"SKU {sku}: {error_msg}")

                    except Exception as e:
                        overall_success = False
                        errors.append(f"SKU {sku}: {e!s}")
            finally:
                if getattr(executor, "browser", None):
                    try:
                        executor.browser.quit()
                    except Exception:
                        pass

            execution_time = time.time() - start_time

            # Convert to unified format
            results = {
                "scraper": scraper_name,
                "skus": skus,
                "mode": "local",
                "success": overall_success,
                "products": products,
                "run_id": None,
                "dataset_id": None,
                "execution_time": execution_time,
                "errors": errors,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Local scraper test failed: {e}")

            results = {
                "scraper": scraper_name,
                "skus": skus,
                "mode": "local",
                "success": False,
                "products": [],
                "run_id": None,
                "dataset_id": None,
                "execution_time": execution_time,
                "errors": [str(e)],
            }

        return results

    @property
    def testing_mode(self) -> TestingMode:
        """Get current testing mode."""
        return self.mode

    def is_local_mode(self) -> bool:
        """Check if running in local mode."""
        return True
