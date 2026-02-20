import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to python path to import scrapers module
sys.path.append(str(Path(__file__).parent.parent))

from scrapers.ai_discovery import AIDiscoveryScraper

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_baseline_test")


async def run_baseline():
    """Run baseline test on all SKUs in ground truth."""
    # Ensure environment variables are set
    if not os.environ.get("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY is not set. Please set it before running.")
        sys.exit(1)
    if not os.environ.get("BRAVE_API_KEY"):
        logger.error("BRAVE_API_KEY is not set. Please set it before running.")
        sys.exit(1)

    # Load ground truth data
    ground_truth_path = Path("tests/fixtures/test_skus_ground_truth.json")
    if not ground_truth_path.exists():
        logger.error(f"Ground truth file not found at {ground_truth_path}")
        sys.exit(1)

    with open(ground_truth_path, "r") as f:
        skus_data = json.load(f)

    logger.info(f"Loaded {len(skus_data)} SKUs for baseline test.")

    # Initialize scraper
    # Set max_steps lower to prevent endless loops
    scraper = AIDiscoveryScraper(headless=True, max_steps=5)

    results = []

    for item in skus_data:
        sku = item["sku"]
        brand = item["brand"]
        product_name = item["name"]

        logger.info(f"\n{'=' * 50}\nStarting extraction for SKU: {sku} - {brand}\n{'=' * 50}")

        start_time = time.time()

        # Format default result for JSON
        result_dict = {
            "sku": sku,
            "expected_brand": brand,
            "success": False,
            "product_name": None,
            "brand": None,
            "size_metrics": None,
            "description": None,
            "images": [],
            "categories": [],
            "url": None,
            "source_website": None,
            "confidence": 0,
            "cost_usd": 0,
            "error": None,
            "extraction_time_seconds": 0,
            "browser_steps_taken": None,
        }

        try:
            # Scrape product
            result = await scraper.scrape_product(sku=sku, product_name=product_name, brand=brand)

            end_time = time.time()
            duration = end_time - start_time

            result_dict.update(
                {
                    "success": result.success,
                    "product_name": result.product_name,
                    "brand": result.brand,
                    "size_metrics": result.size_metrics,
                    "description": result.description,
                    "images": result.images,
                    "categories": result.categories,
                    "url": result.url,
                    "source_website": result.source_website,
                    "confidence": result.confidence,
                    "cost_usd": result.cost_usd,
                    "error": result.error,
                    "extraction_time_seconds": duration,
                }
            )

            logger.info(f"Finished SKU: {sku} in {duration:.2f}s. Success: {result.success}. Cost: ${result.cost_usd:.4f}")
            if result.error:
                logger.error(f"Error for {sku}: {result.error}")

        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"Exception for SKU {sku}: {e}")
            result_dict["error"] = str(e)
            result_dict["extraction_time_seconds"] = duration

        results.append(result_dict)

        # Save intermediate results so we don't lose data if it crashes
        output_path = Path("tests/results/results_v5.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

    logger.info(f"\n{'=' * 50}\nBaseline test complete. Processed {len(results)} SKUs.\n{'=' * 50}")

    # Calculate totals
    total_cost = sum(r["cost_usd"] for r in results)
    total_time = sum(r["extraction_time_seconds"] for r in results)
    successful = sum(1 for r in results if r["success"])

    logger.info(f"Total Cost: ${total_cost:.4f}")
    logger.info(f"Total Time: {total_time:.2f}s")
    logger.info(f"Success Rate: {successful}/{len(results)} ({(successful / len(results)) * 100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(run_baseline())
