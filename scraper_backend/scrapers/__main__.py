"""
CLI entry point for running scrapers.

Usage:
    python -m src.scrapers --file /path/to/skus.xlsx    # Normal run with Excel SKUs
    python -m src.scrapers --test                        # Test mode using YAML test_skus
    python -m src.scrapers --test --scrapers amazon      # Test specific scraper(s)
"""
from __future__ import annotations


import argparse
import os
import sys

import yaml

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scraper_backend.core.settings_manager import settings


def get_test_skus_from_configs(scrapers: list[str] | None = None) -> tuple[list[str], list[str]]:
    """
    Load test_skus from scraper YAML configs.

    Args:
        scrapers: Optional list of specific scrapers to use. If None, uses all.

    Returns:
        Tuple of (unique_skus, scraper_names)
    """

    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")
    all_skus = set()
    used_scrapers = []

    for filename in os.listdir(config_dir):
        if not filename.endswith((".yaml", ".yml")) or filename == "sample_config.yaml":
            continue

        scraper_name = filename.replace(".yaml", "").replace(".yml", "")

        # Filter by requested scrapers if specified
        if scrapers and scraper_name not in [s.lower() for s in scrapers]:
            continue

        config_path = os.path.join(config_dir, filename)
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            test_skus = config.get("test_skus", [])
            if test_skus:
                all_skus.update(test_skus)
                used_scrapers.append(scraper_name)
                print(f"  [OK] {scraper_name}: {len(test_skus)} test SKUs")
        except Exception as e:
            print(f"  [WARN] Failed to load {filename}: {e}")

    return list(all_skus), used_scrapers


def run_test_mode(scrapers: list[str] | None = None, debug_mode: bool = False):
    """Run scrapers in test mode using test_skus from YAML configs.

    Each scraper is run only with its own test_skus, not all SKUs from all configs.
    """
    from scraper_backend.scrapers.main import run_scraping

    print("\n[TEST] TEST MODE - Using test_skus from YAML configurations\n")
    print("=" * 60)

    # Get scraper configs and their individual test_skus
    # Get scraper configs and their individual test_skus
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")
    scraper_test_skus: dict[str, list[str]] = {}

    for filename in os.listdir(config_dir):
        if not filename.endswith((".yaml", ".yml")) or filename == "sample_config.yaml":
            continue

        scraper_name = filename.replace(".yaml", "").replace(".yml", "")

        # Filter by requested scrapers if specified
        if scrapers and scraper_name not in [s.lower() for s in scrapers]:
            continue

        config_path = os.path.join(config_dir, filename)
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            test_skus = config.get("test_skus", [])
            if test_skus:
                scraper_test_skus[scraper_name] = test_skus
                print(f"  [OK] {scraper_name}: {len(test_skus)} test SKUs")
        except Exception as e:
            print(f"  [WARN] Failed to load {filename}: {e}")

    if not scraper_test_skus:
        print("[ERROR] No test SKUs found in configurations!")
        sys.exit(1)

    total_skus = sum(len(skus) for skus in scraper_test_skus.values())
    print(f"\n[INFO] Total test SKUs across all scrapers: {total_skus}")
    print(f"[INFO] Scrapers to run: {', '.join(scraper_test_skus.keys())}")
    print("=" * 60 + "\n")

    # Run each scraper with only its own test_skus
    total_failed = 0

    for scraper_name, test_skus in scraper_test_skus.items():
        print(f"\n{'=' * 60}")
        print(f"[TEST] Running {scraper_name} with {len(test_skus)} test SKUs: {test_skus}")
        print("=" * 60)

        try:
            # Run this single scraper with only its test SKUs
            run_scraping(
                skus=test_skus,
                selected_sites=[scraper_name.replace("_", " ").title()],
                test_mode=True,
                debug_mode=debug_mode,
            )
        except Exception as e:
            print(f"[ERROR] {scraper_name} failed: {e}")
            total_failed += len(test_skus)
            continue

    print(f"\n{'=' * 60}")
    print("[TEST] ALL SCRAPER TESTS COMPLETE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Product Scraper CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.scrapers --file data/spreadsheets/products.xlsx
  python -m src.scrapers --test
  python -m src.scrapers --test --scrapers amazon petfoodex
        """,
    )

    parser.add_argument("--file", "-f", type=str, help="Path to Excel file containing SKUs")

    parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Run in test mode using test_skus from YAML configs",
    )

    parser.add_argument(
        "--scrapers", "-s", nargs="+", type=str, help="Specific scrapers to run (default: all)"
    )

    parser.add_argument(
        "--max-workers", "-w", type=int, help="Maximum number of concurrent worker threads"
    )

    parser.add_argument(
        "--scraper-workers",
        nargs="+",
        help="Worker counts per scraper (e.g. 'amazon=2 chewy=1')",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.test and not args.file:
        parser.error("Either --file or --test must be specified")

    # Parse scraper workers if provided
    scraper_workers = {}
    if args.scraper_workers:
        for item in args.scraper_workers:
            try:
                name, count = item.split("=")
                scraper_workers[name] = int(count)
            except ValueError:
                print(f"[WARN] Invalid format for worker count: {item}. Use name=count")

    # Force reload settings to ensure we get the latest DB value
    try:
        settings.reload()
        # Fallback to DB setting if CLI flag is not set
        debug_mode = args.debug or settings.debug_mode
        if debug_mode:
            print("[INFO] Debug mode enabled")
    except Exception as e:
        print(f"[WARN] Failed to load settings: {e}")
        debug_mode = args.debug

    if args.test:
        run_test_mode(scrapers=args.scrapers, debug_mode=debug_mode)
    else:
        from scraper_backend.scrapers.main import run_scraping

        if not os.path.exists(args.file):
            print(f"[ERROR] File not found: {args.file}")
            sys.exit(1)

        # Convert scraper names to title case for run_scraping
        selected = None
        if args.scrapers:
            selected = [s.replace("_", " ").title() for s in args.scrapers]

        run_scraping(
            file_path=args.file,
            selected_sites=selected,
            max_workers=args.max_workers,
            scraper_workers=scraper_workers,
            debug_mode=debug_mode,
        )


if __name__ == "__main__":
    main()
