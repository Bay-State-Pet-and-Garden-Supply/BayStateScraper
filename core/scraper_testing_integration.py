"""
Scraper Testing Integration
Extends local testing with scraper testing capabilities.
"""
from __future__ import annotations


import logging
from pathlib import Path
from typing import Any

from utils.testing.scraper_validator import ScraperValidator

from .scraper_testing_client import ScraperTestingClient, TestingMode

logger = logging.getLogger(__name__)


class ScraperIntegrationTester:
    """
    Extended integration tester that supports scraper testing modes.
    """

    def __init__(
        self,
        test_data_path: str | None = None,
        mode: TestingMode = TestingMode.LOCAL,
    ):
        """
        Initialize the scraper integration tester.

        Args:
            test_data_path: Path to test data JSON file
            mode: Testing mode (LOCAL supported)
        """
        self.project_root = Path(__file__).parent.parent.parent
        self.test_data_path = test_data_path or "tests/fixtures/scraper_test_data.json"
        self.mode = mode

        # Initialize validator
        self.validator = ScraperValidator()

        # Initialize testing client
        # Always use headless mode as per user requirement
        self.testing_client = ScraperTestingClient(mode=mode, headless=True)

    def get_test_skus(self, scraper_name: str) -> list[str]:
        """Get test SKUs for a scraper from Supabase."""
        from core.database.supabase_sync import supabase_sync

        scraper = supabase_sync.get_scraper(scraper_name)
        if not scraper:
            return ["035585499741"]  # Default fallback

        return scraper.get("test_skus") or ["035585499741"]

    def get_available_scrapers(self) -> list[str]:
        """Get list of available scraper names from Supabase."""
        from core.database.supabase_sync import supabase_sync

        scrapers = supabase_sync.get_all_scrapers(include_disabled=True)
        return sorted([s["name"] for s in scrapers])

    async def run_scraper_test(
        self, scraper_name: str, skus: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Run a scraper test in the configured mode.

        Args:
            scraper_name: Name of the scraper to test
            skus: Optional list of SKUs, uses test data if not provided

        Returns:
            Dict with test results
        """
        if skus is None:
            skus = self.get_test_skus(scraper_name)

        # Ensure skus is a list
        if not isinstance(skus, list):
            skus = [str(skus)] if skus else ["035585499741"]

        # At this point skus is guaranteed to be List[str]
        assert isinstance(skus, list) and all(isinstance(s, str) for s in skus)

        print(f"\n{'=' * 60}")
        print(f"TESTING SCRAPER: {scraper_name.upper()} ({self.mode.value.upper()} MODE)")
        print(f"SKUs: {skus}")
        print(f"{'=' * 60}")

        # Run the scraper
        async with self.testing_client:
            run_results = await self.testing_client.run_scraper(scraper_name, skus)

        # Validate results
        validation_results: Any = {}
        if run_results["success"] and run_results["products"]:
            validation_results = self.validator.validate_product_data(
                run_results["products"], scraper_name
            )

        # Combine results
        test_results = {
            "scraper": scraper_name,
            "mode": self.mode.value,
            "run_results": run_results,
            "validation_results": validation_results,
            "overall_success": run_results["success"] and not validation_results.get("errors", []),
        }

        # Print summary
        self._print_test_summary(test_results)

        return test_results

    async def run_all_scrapers_test(
        self, skip_failing: bool = True, scrapers: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Test all available scrapers in the configured mode.

        Args:
            skip_failing: Whether to continue testing other scrapers if one fails
            scrapers: Optional list of scraper names to test. If None, tests all available.

        Returns:
            Dict with results for all scrapers
        """
        if scrapers is None:
            scrapers = self.get_available_scrapers()
        results: dict[str, Any] = {
            "total_scrapers": len(scrapers),
            "successful_scrapers": 0,
            "failed_scrapers": 0,
            "scraper_results": {},
            "summary": {},
            "mode": self.mode.value,
        }

        print(f"\n{'=' * 80}")
        print(
            f"RUNNING {self.mode.value.upper()} INTEGRATION TESTS FOR ALL {len(scrapers)} SCRAPERS"
        )
        print(f"{'=' * 80}")

        for scraper_name in scrapers:
            try:
                test_result = await self.run_scraper_test(scraper_name)
                results["scraper_results"][scraper_name] = test_result

                if test_result["overall_success"]:
                    results["successful_scrapers"] += 1
                else:
                    results["failed_scrapers"] += 1

                if not skip_failing and not test_result["overall_success"]:
                    print(f"STOP: Stopping tests due to failure in {scraper_name}")
                    break

            except Exception as e:
                print(f"ERROR: Unexpected error testing {scraper_name}: {e}")
                results["scraper_results"][scraper_name] = {
                    "scraper": scraper_name,
                    "mode": self.mode.value,
                    "overall_success": False,
                    "error": str(e),
                }
                results["failed_scrapers"] += 1

                if not skip_failing:
                    break

        # Generate summary
        results["summary"] = self._generate_summary(results)

        print(f"\n{'=' * 80}")
        print("FINAL SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total Scrapers: {results['total_scrapers']}")
        print(f"Successful: {results['successful_scrapers']}")
        print(f"Failed: {results['failed_scrapers']}")
        print(f"Success Rate: {results['summary']['success_rate']:.1f}%")
        print(f"Testing Mode: {self.mode.value.upper()}")

        if results["failed_scrapers"] > 0:
            print("\nFAILED SCRAPERS:")
            for name, result in results["scraper_results"].items():
                if not result.get("overall_success", False):
                    print(f"  - {name}")
        else:
            print(f"\nALL SCRAPERS PASSED {self.mode.value.upper()} TESTS")

        return results

    def _print_test_summary(self, test_results: dict[str, Any]) -> None:
        """Print a summary of test results for a single scraper."""
        scraper = test_results["scraper"]
        mode = test_results["mode"]
        run_results = test_results["run_results"]
        validation_results = test_results["validation_results"]

        print(f"\nTEST SUMMARY: {scraper} ({mode.upper()})")

        # Run results
        if run_results["success"]:
            print("SUCCESS: Execution")
            print(f"   Products found: {len(run_results['products'])}")
            if run_results.get("run_id"):
                print(f"   Run ID: {run_results['run_id']}")
            if run_results.get("dataset_id"):
                print(f"   Dataset ID: {run_results['dataset_id']}")
        else:
            print("FAILED: Execution")
            for error in run_results["errors"][:3]:
                print(f"   - {error}")

        # Validation results
        if validation_results:
            valid = validation_results.get("valid_products", 0)
            total = validation_results.get("total_products", 0)
            score = validation_results.get("data_quality_score", 0)

            print(f"VALIDATION: {valid}/{total} products valid")
            print(f"   Data Quality Score: {score:.1f}")

            # Print field coverage
            field_coverage = validation_results.get("field_coverage", {})
            if field_coverage:
                print("   Field Coverage:")
                for field, coverage in field_coverage.items():
                    status = "PASS" if coverage == 100.0 else "WARN" if coverage > 0 else "FAIL"
                    print(f"     {status} {field}: {coverage:.1f}%")

            if validation_results.get("errors"):
                print(f"   Errors: {len(validation_results['errors'])}")
                for error in validation_results["errors"][:3]:  # Show first 3 errors
                    print(f"     - {error}")
            if validation_results.get("warnings"):
                print(f"   Warnings: {len(validation_results['warnings'])}")
                for warning in validation_results["warnings"][:3]:  # Show first 3 warnings
                    print(f"     - {warning}")

        # Overall result
        if test_results["overall_success"]:
            print("OVERALL: PASSED")
        else:
            print("OVERALL: FAILED")

    def _generate_summary(self, results: dict[str, Any]) -> dict[str, Any]:
        """Generate a summary of all test results."""
        summary = {
            "total_scrapers": results["total_scrapers"],
            "successful_scrapers": results["successful_scrapers"],
            "failed_scrapers": results["failed_scrapers"],
            "success_rate": 0.0,
            "failed_scrapers_list": [],
            "common_errors": {},
            "average_quality_score": 0.0,
        }

        if results["total_scrapers"] > 0:
            summary["success_rate"] = (
                results["successful_scrapers"] / results["total_scrapers"]
            ) * 100

        quality_scores = []
        for scraper_name, test_result in results["scraper_results"].items():
            if not test_result.get("overall_success", False):
                summary["failed_scrapers_list"].append(scraper_name)

            # Collect common errors
            run_errors = test_result.get("run_results", {}).get("errors", [])
            validation_errors = test_result.get("validation_results", {}).get("errors", [])

            for error in run_errors + validation_errors:
                if error in summary["common_errors"]:
                    summary["common_errors"][error] += 1
                else:
                    summary["common_errors"][error] = 1

            # Collect quality scores
            score = test_result.get("validation_results", {}).get("data_quality_score", 0)
            if score > 0:
                quality_scores.append(score)

        if quality_scores:
            summary["average_quality_score"] = sum(quality_scores) / len(quality_scores)

        return summary
