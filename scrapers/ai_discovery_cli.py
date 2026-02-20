#!/usr/bin/env python3
"""
CLI for AI Discovery Scraper.

Run standalone AI product discovery:
    python -m scrapers.ai_discovery_cli --sku 12345 --brand "Purina" --name "Pro Plan"

"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(
        description="AI Discovery Scraper - Universal product extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape a Purina product
  python -m scrapers.ai_discovery_cli --sku 12345 --brand "Purina" --name "Pro Plan"
  
  # Scrape with custom options
  python -m scrapers.ai_discovery_cli --sku 67890 --brand "Blue Buffalo" \
         --max-steps 20 --model gpt-4o
        """,
    )

    parser.add_argument("--sku", "-s", required=True, help="Product SKU or identifier")
    parser.add_argument("--brand", "-b", help="Product brand (helps identify manufacturer site)")
    parser.add_argument("--name", "-n", help="Product name (helps search accuracy)")
    parser.add_argument("--category", "-c", help="Product category (optional)")
    parser.add_argument("--max-steps", type=int, default=15, help="Maximum browser actions (default: 15)")
    parser.add_argument("--max-results", type=int, default=5, help="Number of search results to analyze (default: 5)")
    parser.add_argument("--confidence", type=float, default=0.7, help="Minimum confidence threshold (default: 0.7)")
    parser.add_argument("--model", default="gpt-4o-mini", choices=["gpt-4o-mini", "gpt-4o"], help="LLM model to use (default: gpt-4o-mini)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode (default: True)")
    parser.add_argument("--visible", action="store_true", help="Show browser window (sets headless=False)")
    parser.add_argument("--output", "-o", help="Output file for results (JSON)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Import here to avoid slow imports during arg parsing
    from scrapers.ai_discovery import AIDiscoveryScraper

    logger.info(f"🔍 Starting AI Discovery Scraper for SKU: {args.sku}")

    # Create scraper
    scraper = AIDiscoveryScraper(
        headless=not args.visible,
        max_search_results=args.max_results,
        max_steps=args.max_steps,
        confidence_threshold=args.confidence,
        llm_model=args.model,
    )

    # Run extraction
    start_time = asyncio.get_event_loop().time()
    result = await scraper.scrape_product(
        sku=args.sku,
        product_name=args.name,
        brand=args.brand,
        category=args.category,
    )
    duration = asyncio.get_event_loop().time() - start_time

    # Display results
    print("\n" + "=" * 60)
    print("📊 EXTRACTION RESULTS")
    print("=" * 60)

    if result.success:
        print(f"✅ SUCCESS (Confidence: {result.confidence:.0%})")
        print(f"\n📦 Product: {result.product_name or 'N/A'}")
        print(f"🏢 Brand: {result.brand or 'N/A'}")
        print(f"📏 Size: {result.size_metrics or 'N/A'}")
        print(f"📍 Source: {result.source_website or 'N/A'}")
        print(f"🏷️ Categories: {', '.join(result.categories) if result.categories else 'N/A'}")
        print(f"\n📝 Description:")
        desc = result.description or "N/A"
        if len(desc) > 200:
            desc = desc[:200] + "..."
        print(f"  {desc}")
        print(f"\n🖼️  Images: {len(result.images or [])} found")
        for i, img in enumerate((result.images or [])[:3], 1):
            print(f"  {i}. {img[:80]}...")
        if len(result.images or []) > 3:
            print(f"  ... and {len(result.images or []) - 3} more")
    else:
        print(f"❌ FAILED")
        print(f"\nError: {result.error or 'Unknown error'}")

    print(f"\n💵 Cost: ${result.cost_usd:.4f}")
    print(f"⏱️  Duration: {duration:.1f}s")
    print("=" * 60)

    # Save to file if requested
    if args.output:
        output_data = {
            "success": result.success,
            "sku": result.sku,
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
            "duration_seconds": duration,
        }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)

        logger.info(f"💾 Results saved to: {args.output}")

    # Exit with appropriate code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
