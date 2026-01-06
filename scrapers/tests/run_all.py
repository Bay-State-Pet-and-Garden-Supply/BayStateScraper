from __future__ import annotations

import asyncio
import sys

from core.scraper_testing_integration import ScraperIntegrationTester


async def run_all():
    tester = ScraperIntegrationTester()
    scrapers = tester.get_available_scrapers()
    print(f"Found scrapers: {scrapers}")

    failed = []
    for scraper in scrapers:
        print(f"\nRunning test for: {scraper}")
        # Skip scrapers that require login or are known to be problematic in CI/headless if needed
        # But for now we try all.
        try:
            result = await tester.run_scraper_test(scraper)
            if not result.get("overall_success", False):
                failed.append(scraper)
        except Exception as e:
            print(f"Exception running {scraper}: {e}")
            failed.append(scraper)

    if failed:
        print(f"\nFAILED scrapers: {failed}")
        sys.exit(1)
    else:
        print("\nALL PASSED!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_all())
