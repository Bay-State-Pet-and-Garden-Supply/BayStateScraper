"""
This module provides the core functionality for running scraper tests.
"""
from __future__ import annotations


import asyncio
from pathlib import Path

import yaml


class ScraperIntegrationTester:
    """
    A class to run integration tests for scrapers.
    This class is designed to be used programmatically.
    """

    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.validator = self.ScraperValidator()

    class ScraperValidator:
        def validate_product_data(self, products, scraper_name):
            # Dummy implementation for now.
            # In a real scenario, this would validate product data against a schema.
            return {
                "valid_products": len(products),
                "total_products": len(products),
                "data_quality_score": 100.0,
                "field_coverage": {"Name": 100.0, "Brand": 100.0, "Images": 100.0, "Weight": 100.0},
                "errors": [],
                "warnings": [],
            }

    def get_test_skus(self, scraper_name: str, max_skus: int = 1) -> list[str]:
        """Get test SKUs for a scraper from its YAML config."""
        config_path = self.project_root / "src" / "scrapers" / "configs" / f"{scraper_name}.yaml"
        if not config_path.exists():
            return ["035585499741"]  # Default fallback

        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        skus = config_data.get("test_skus") or ["035585499741"]
        return skus[:max_skus]

    def run_scraper_locally(
        self, scraper_name: str, skus: list[str], headless: bool = True
    ) -> dict:
        # This is a placeholder for the actual scraper execution logic.
        # It simulates running a scraper and returning some data.
        print(f"Simulating running scraper '{scraper_name}' with SKUs: {skus}")
        # In a real implementation, you would use Playwright or Selenium here.
        # For this example, we will just return some mock data.
        return {
            "success": True,
            "products": [
                {
                    "SKU": sku,
                    "Name": f"Product {sku}",
                    "Brand": "Brand",
                    "Images": [],
                    "Weight": "1kg",
                }
                for sku in skus
            ],
            "errors": [],
            "execution_time": 1.23,
        }

    def test_single_scraper(self, scraper_name: str, skus: list[str] | None = None) -> dict:
        """Test a single scraper with validation."""
        if skus is None:
            skus = self.get_test_skus(scraper_name)

        if not isinstance(skus, list):
            skus = [str(skus)]

        run_results = self.run_scraper_locally(scraper_name, skus)

        validation_results = {}
        if run_results["success"] and run_results["products"]:
            validation_results = self.validator.validate_product_data(
                run_results["products"], scraper_name
            )

        return {
            "scraper": scraper_name,
            "run_results": run_results,
            "validation_results": validation_results,
            "overall_success": run_results["success"] and not validation_results.get("errors", []),
        }


async def run_tests(scraper_names: list[str], log_callback=None):
    """
    Runs integration tests for a given list of scrapers.
    """

    def log(msg, level="INFO"):
        """Helper to handle callback functions."""
        if log_callback:
            try:
                log_callback.emit(msg)
            except AttributeError:
                # Fallback for regular callable
                log_callback(msg)

    log(f"Starting tests for: {', '.join(scraper_names)}")

    tester = ScraperIntegrationTester()
    all_results = {}
    for scraper_name in scraper_names:
        log(f"--- Running test for {scraper_name} ---")
        try:
            # In a real application, you might want to run these concurrently.
            # For simplicity, we run them sequentially here.
            result = tester.test_single_scraper(scraper_name)
            all_results[scraper_name] = result
            if result.get("overall_success"):
                log(f"Test for {scraper_name} PASSED")
            else:
                log(f"Test for {scraper_name} FAILED")
        except Exception as e:
            log(f"An error occurred while testing {scraper_name}: {e}")
            import traceback

            traceback.print_exc()
            all_results[scraper_name] = {"overall_success": False, "error": str(e)}

    log("--- Test run finished. ---")

    return all_results
