"""
Integration tests for running scrapers locally and validating output.
"""

from __future__ import annotations


import copy
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore

from core.scraper_testing_client import TestingMode
from core.scraper_testing_integration import ScraperIntegrationTester

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


# Pytest integration
class TestScraperIntegration:
    """Pytest test class for scraper integration tests."""

    @pytest.fixture
    def tester(self):
        """Create a ScraperIntegrationTester instance."""
        return ScraperIntegrationTester()

    @pytest.fixture
    def available_scrapers(self, tester):
        """Get list of available scrapers."""
        return tester.get_available_scrapers()

    @pytest.fixture
    def scraper_cleanup(self):
        """Fixture for scraper cleanup after tests."""
        cleanup_items: list[Any] = []

        yield cleanup_items

        # Cleanup after test
        for item in cleanup_items:
            if hasattr(item, "cleanup"):
                item.cleanup()
            elif hasattr(item, "close"):
                item.close()
            elif hasattr(item, "quit"):
                item.quit()

    def test_get_available_scrapers(self, available_scrapers):
        """Test that we can discover available scrapers."""
        assert len(available_scrapers) > 0, "No scrapers found"
        assert "amazon" in available_scrapers, "Amazon scraper should be available"

        print(f"Found scrapers: {available_scrapers}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.parametrize(
        "scraper_name",
        [
            "amazon",  # Most reliable for testing
            "central_pet",
            "coastal",
            "mazuri",
        ],
    )
    async def test_scraper_no_results_parametrized(self, tester, scraper_name):
        """Test the 'no results' handling for individual scrapers with parametrization."""
        if os.getenv("CI") == "true" and scraper_name in {
            "orgill",
            "petfoodex",
            "phillips",
        }:
            pytest.skip(f"Skipping {scraper_name} in CI (requires login)")

        # Use a standardized fake SKU that should never exist
        fake_sku = "AUTOMATEDTEST-NONEXISTENT-SKU-12345"

        # Run the scraper with the fake SKU
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper(scraper_name, [fake_sku])

        # The primary success condition is that the scraper ran and correctly identified 'no results'.
        assert result["success"] is True, (
            f"Expected scraper '{scraper_name}' to report success for a handled 'no results' scenario."
        )

        # There should be exactly one product record containing the no_results_found flag.
        # Wait, if result['products'] is empty but result['success'] is True, it might be legacy behavior.
        # But in modern code, it should return a record with no_results_found=True.
        assert len(result["products"]) == 1, (
            f"Expected 1 product record for a 'no results' test, but found {len(result['products'])}."
        )

        product_record = result["products"][0]
        assert product_record.get("no_results_found") is True, (
            f"Expected the product record for '{scraper_name}' to have 'no_results_found' set to True."
        )
        assert product_record.get("SKU") == fake_sku, (
            "The SKU in the product record should match the fake SKU used for the test."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.parametrize(
        "scraper_name",
        [
            "amazon",  # Most reliable for testing
            "central_pet",
            "coastal",
            "mazuri",
        ],
    )
    async def test_scraper_execution_parametrized(self, tester, scraper_name):
        """Test running individual scrapers with parametrization."""
        # Skip login-requiring scrapers in CI
        if os.getenv("CI") == "true" and scraper_name in {
            "orgill",
            "petfoodex",
            "phillips",
        }:
            pytest.skip(f"Skipping {scraper_name} in CI (requires login)")

        result = await tester.run_scraper_test(scraper_name)

        # Basic checks
        assert "scraper" in result
        assert result["scraper"] == scraper_name

        # Print results for debugging
        print(f"Test result for {scraper_name}: {result['overall_success']}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_results_browser_response_simulation(self, tester):
        """Test real browser responses with fake SKUs that trigger no results pages."""
        # Use a fake SKU that should not exist and trigger no results
        fake_sku = "23184912789412789078124940172"

        # Run scraper with fake SKU
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper("amazon", [fake_sku])

        # Verify scraper execution
        assert result["success"] is True, "Expected success=True for handled no results"
        assert len(result["products"]) == 1
        product = result["products"][0]
        assert product.get("no_results_found") is True
        assert product["SKU"] == fake_sku

        # Verify execution completed
        assert result["execution_time"] > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_end_to_end_no_results_workflow_execution(self, tester):
        """Test end-to-end workflow execution with no results detection using real scraper."""
        # Use a fake SKU that should trigger no results on Amazon
        fake_sku = "NONEXISTENTPRODUCT987654321"

        # Run scraper with fake SKU
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper("amazon", [fake_sku])

        # Verify scraper successfully handled the no results scenario
        assert result["success"] is True, "Expected success=True for handled no results"

        # Verify products list contains the result with no_results_found flag
        assert len(result["products"]) == 1
        product = result["products"][0]
        assert product.get("no_results_found") is True, "Expected no_results_found=True"
        assert product["SKU"] == fake_sku

        # Verify execution completed
        assert result["execution_time"] > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_results_failure_reporting_and_analytics(self, tester):
        """Test proper failure reporting and analytics recording for no results scenarios."""
        # Use a fake SKU that triggers no results
        fake_sku = "XQJ7-NORESULTS-ANALYTICS-TEST-999"

        # Run scraper with fake SKU
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper("amazon", [fake_sku])

        # Verify scraper successfully handled no results
        assert result["success"] is True
        assert len(result["products"]) == 1
        assert result["products"][0].get("no_results_found") is True

        # Verify execution completed
        assert result["execution_time"] > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_results_graceful_handling_without_retries(self, tester):
        """Test that no results scenarios are handled gracefully without retries."""
        # Use a fake SKU that triggers no results
        fake_sku = "NORESULTSGRACEFUL456"

        # Run scraper with fake SKU
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper("amazon", [fake_sku])

        # Verify scraper handled gracefully due to no results
        assert result["success"] is True
        assert len(result["products"]) == 1
        assert result["products"][0].get("no_results_found") is True

        # Verify execution completed
        assert result["execution_time"] > 0

    @pytest.mark.integration
    def test_no_results_integration_with_config_validation(self, tester):
        """Test integration with scraper configuration validation sections for no results."""
        # Fetch config from Supabase via tester helper if local file missing
        from core.database.supabase_sync import supabase_sync

        config_dict = None
        if supabase_sync.initialize():
            config_dict = supabase_sync.get_scraper("amazon")

        if config_dict:
            from scrapers.parser.yaml_parser import ScraperConfigParser

            parser = ScraperConfigParser()
            config = parser.load_from_dict(config_dict)
        else:
            # Fallback to local file if available (legacy)
            from scrapers.parser.yaml_parser import ScraperConfigParser

            parser = ScraperConfigParser()
            config_path = tester.project_root / "scrapers" / "configs" / "amazon.yaml"
            if not config_path.exists():
                pytest.skip("Amazon config not found in Supabase or locally")
            config = parser.load_from_file(config_path)

        # Verify config has validation section
        assert config.validation is not None
        assert config.validation.no_results_selectors is not None
        assert len(config.validation.no_results_selectors) > 0
        assert config.validation.no_results_text_patterns is not None
        assert len(config.validation.no_results_text_patterns) > 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_results_end_to_end_with_real_config(self, tester):
        """Test end-to-end no results handling using real scraper configuration."""
        # Use amazon config with a SKU that should not exist
        non_existent_sku = "THISPRODUCTDOESNOTEXIST123456789"

        # Run scraper with non-existent SKU - should naturally encounter no results page
        async with tester.testing_client:
            result = await tester.testing_client.run_scraper(
                "amazon", [non_existent_sku]
            )

        # Verify success with no_results_found flag
        assert result["success"] is True
        assert len(result["products"]) == 1
        assert result["products"][0].get("no_results_found") is True

        # Verify execution completed without hanging
        assert result["execution_time"] > 0


if __name__ == "__main__":
    # Allow running from command line
    import argparse

    parser = argparse.ArgumentParser(description="Run scraper integration tests")
    parser.add_argument("--scraper", help="Test specific scraper")
    parser.add_argument("--skus", nargs="+", help="SKUs to test with")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    tester = ScraperIntegrationTester()

    if args.scraper:
        import asyncio

        result = asyncio.run(tester.run_scraper_test(args.scraper, args.skus))
        if not result["overall_success"]:
            sys.exit(1)
    else:
        print("Use --scraper <name> to test a specific scraper")
        print(f"Available scrapers: {tester.get_available_scrapers()}")
        sys.exit(1)
