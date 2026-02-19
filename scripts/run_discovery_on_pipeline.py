#!/usr/bin/env python3
"""
Run AI Discovery Scraper on all products in the ingestion pipeline.

This script:
1. Fetches all products from products_ingestion that need enhancement
2. Runs the AI Discovery scraper on each product
3. Updates the products with enhanced data from manufacturer websites
4. Tracks costs and success rates

Usage:
    python scripts/run_discovery_on_pipeline.py --limit 100
    python scripts/run_discovery_on_pipeline.py --brand "Purina"
    python scripts/run_discovery_on_pipeline.py --dry-run
"""

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.ai_discovery import AIDiscoveryScraper, DiscoveryResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/discovery_pipeline.log")],
)
logger = logging.getLogger(__name__)


async def fetch_pipeline_products(
    limit: Optional[int] = None,
    brand: Optional[str] = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Fetch products from the ingestion pipeline.

    In a real implementation, this would query your Supabase database.
    For now, we'll use a mock implementation.
    """
    logger.info("Fetching products from ingestion pipeline...")

    # Mock data - in production, query Supabase
    products = [
        {
            "sku": "TEST001",
            "product_name": "Pro Plan Chicken & Rice",
            "brand": "Purina",
            "category": "Dog Food",
            "current_data": {
                "price": "$45.99",
                "description": "High protein dog food",
            },
        },
        {"sku": "TEST002", "product_name": "Life Protection Formula", "brand": "Blue Buffalo", "category": "Dog Food", "current_data": {}},
    ]

    if brand:
        products = [p for p in products if p.get("brand", "").lower() == brand.lower()]

    if limit:
        products = products[:limit]

    logger.info(f"Found {len(products)} products to process")
    return products


async def enhance_product(
    scraper: AIDiscoveryScraper,
    product: dict[str, Any],
    dry_run: bool = False,
) -> DiscoveryResult:
    """Enhance a single product using AI Discovery."""
    sku = product.get("sku")
    product_name = product.get("product_name")
    brand = product.get("brand")

    logger.info(f"Processing {brand} {product_name} (SKU: {sku})")

    if dry_run:
        logger.info(f"[DRY RUN] Would scrape: {sku}")
        return DiscoveryResult(
            success=True,
            sku=sku,
            product_name=product_name,
            brand=brand,
            cost_usd=0.0,
        )

    result = await scraper.scrape_product(
        sku=sku,
        product_name=product_name,
        brand=brand,
    )

    return result


async def update_product_in_pipeline(
    sku: str,
    result: DiscoveryResult,
    dry_run: bool = False,
) -> bool:
    """Update the product in the pipeline with discovered data.

    In production, this would update your Supabase database.
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would update {sku} with discovered data")
        return True

    # In production: update Supabase
    # await supabase.from('products_ingestion').update({...}).eq('sku', sku)

    logger.info(f"Updated {sku} in pipeline")
    return True


async def main():
    parser = argparse.ArgumentParser(
        description="Run AI Discovery on all pipeline products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all products (dry run)
  python scripts/run_discovery_on_pipeline.py --dry-run
  
  # Process 100 products
  python scripts/run_discovery_on_pipeline.py --limit 100
  
  # Process only Purina products
  python scripts/run_discovery_on_pipeline.py --brand "Purina"
        """,
    )

    parser.add_argument("--limit", "-l", type=int, help="Maximum number of products to process")
    parser.add_argument("--brand", "-b", help="Only process products from this brand")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--max-steps", type=int, default=15, help="Maximum browser actions per extraction (default: 15)")
    parser.add_argument("--model", default="gpt-4o-mini", choices=["gpt-4o-mini", "gpt-4o"], help="LLM model to use (default: gpt-4o-mini)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode (default: True)")
    parser.add_argument("--visible", action="store_true", help="Show browser window (sets headless=False)")
    parser.add_argument("--output", "-o", default="logs/discovery_results.json", help="Output file for results (JSON)")

    args = parser.parse_args()

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    logger.info("=" * 60)
    logger.info("AI Discovery Pipeline Runner")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No actual scraping will occur")

    # Fetch products
    products = await fetch_pipeline_products(
        limit=args.limit,
        brand=args.brand,
        dry_run=args.dry_run,
    )

    if not products:
        logger.warning("No products found to process")
        return

    # Initialize scraper
    scraper = AIDiscoveryScraper(
        headless=not args.visible,
        max_steps=args.max_steps,
        llm_model=args.model,
    )

    # Process all products
    results = []
    total_cost = 0.0
    success_count = 0

    start_time = datetime.now()

    for i, product in enumerate(products, 1):
        logger.info(f"\n[{i}/{len(products)}] Processing {product.get('sku')}...")

        try:
            result = await enhance_product(scraper, product, dry_run=args.dry_run)

            results.append(
                {
                    "sku": result.sku,
                    "success": result.success,
                    "product_name": result.product_name,
                    "brand": result.brand,
                    "price": result.price,
                    "availability": result.availability,
                    "url": result.url,
                    "source_website": result.source_website,
                    "confidence": result.confidence,
                    "cost_usd": result.cost_usd,
                    "error": result.error,
                }
            )

            total_cost += result.cost_usd

            if result.success:
                success_count += 1
                logger.info(f"✅ Success: {result.product_name} from {result.source_website}")

                # Update pipeline
                await update_product_in_pipeline(result.sku, result, dry_run=args.dry_run)
            else:
                logger.warning(f"❌ Failed: {result.error}")

        except Exception as e:
            logger.error(f"Error processing {product.get('sku')}: {e}")
            results.append(
                {
                    "sku": product.get("sku"),
                    "success": False,
                    "error": str(e),
                }
            )

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("DISCOVERY PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Products processed: {len(products)}")
    logger.info(f"Successful: {success_count} ({success_count / len(products) * 100:.1f}%)")
    logger.info(f"Failed: {len(products) - success_count}")
    logger.info(f"Total cost: ${total_cost:.4f}")
    logger.info(f"Average cost per product: ${total_cost / len(products):.4f}")
    logger.info(f"Duration: {duration:.1f}s ({duration / len(products):.1f}s per product)")
    logger.info("=" * 60)

    # Save results
    output_data = {
        "run_date": start_time.isoformat(),
        "config": {
            "limit": args.limit,
            "brand": args.brand,
            "model": args.model,
            "max_steps": args.max_steps,
            "dry_run": args.dry_run,
        },
        "summary": {
            "total": len(products),
            "success": success_count,
            "failed": len(products) - success_count,
            "success_rate": success_count / len(products) if products else 0,
            "total_cost_usd": total_cost,
            "duration_seconds": duration,
        },
        "results": results,
    }

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)

    logger.info(f"\n💾 Results saved to: {args.output}")

    # Exit with appropriate code
    sys.exit(0 if success_count == len(products) else 1)


if __name__ == "__main__":
    asyncio.run(main())
