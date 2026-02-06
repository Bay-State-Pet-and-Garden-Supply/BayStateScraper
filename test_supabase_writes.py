#!/usr/bin/env python3
"""
Test Supabase Write Operations for BayStateScraper.

Usage:
    python test_supabase_writes.py
"""

import sys
import os
from datetime import datetime
from uuid import uuid4

# Add project root to path
project_root = r"C:\Users\thoma\OneDrive\Desktop\scripts\BayState\BayStateScraper"
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.chdir(project_root)

from dotenv import load_dotenv

load_dotenv()


def test_supabase_writes():
    from supabase import create_client, Client
    import asyncio

    async def run_test():
        print("=" * 60)
        print("Testing Supabase Write Operations")
        print("=" * 60)

        from core.api_client import ScraperAPIClient

        client = ScraperAPIClient()

        print("\n[1] Fetching Supabase config from API...")
        supabase_config = client.get_supabase_config()

        if not supabase_config:
            print("FAIL: Could not fetch Supabase config")
            return False

        supabase_url = supabase_config["supabase_url"]
        service_key = supabase_config["supabase_realtime_key"]

        print(f"  URL: {supabase_url}")

        try:
            supabase: Client = create_client(supabase_url, service_key)
            print("  OK: Supabase client created")
        except Exception as e:
            print(f"FAIL: Could not create Supabase client: {e}")
            return False

        # [2] Check tables exist
        print("\n[2] Checking required tables...")
        required_tables = ["scrape_jobs", "products_ingestion", "scrape_results", "scraper_runners"]

        for table in required_tables:
            try:
                result = supabase.from_(table).select("*").limit(1).execute()
                print(f"  OK: Table '{table}' exists")
            except Exception as e:
                print(f"  WARN: Table '{table}' - {str(e)[:60]}")

        # [3] Check for products to scrape
        print("\n[3] Checking products_ingestion for SKUs...")
        try:
            result = supabase.from_("products_ingestion").select("*").limit(5).execute()
            products = result.data
            print(f"  Found {len(products)} products")

            if products:
                for p in products[:3]:
                    print(f"    - SKU: {p.get('sku', 'N/A')}")
                    print(f"      Pipeline status: {p.get('pipeline_status', 'unknown')}")
                    print()
            else:
                print("  NOTE: products_ingestion is empty")
                print("  Scraper jobs need products in this table")

        except Exception as e:
            print(f"  WARN: Could not query products: {e}")

        # [4] Check scrape_jobs table
        print("\n[4] Checking scrape_jobs table...")
        try:
            result = supabase.from_("scrape_jobs").select("*").order("created_at", desc=True).limit(5).execute()
            jobs = result.data
            print(f"  Found {len(jobs)} jobs")
        except Exception as e:
            print(f"  WARN: Could not query jobs: {e}")

        # [5] Test write capability
        print("\n[5] Testing write capability to scrape_results...")

        test_job_uuid = str(uuid4())
        test_data = {
            "job_id": test_job_uuid,
            "runner_name": "test-runner",
            "data": {"test_sku": {"test_scraper": {"price": 99.99, "title": "Test Product", "scraped_at": datetime.now().isoformat()}}},
        }

        try:
            result = supabase.from_("scrape_results").insert(test_data).execute()

            if result.data:
                print(f"  OK: Successfully inserted test record")
                print(f"  Inserted ID: {result.data[0].get('id', 'N/A')}")

                # Clean up
                supabase.from_("scrape_results").delete().eq("job_id", test_job_uuid).execute()
                print("  OK: Cleaned up test record")

                print("\n" + "=" * 60)
                print("SUCCESS: Supabase write test passed!")
                print("=" * 60)
                print("\nNOTE: Writes work via scrape_results table.")
                print("Production writes go through callback API:")
                print("  Scraper -> /api/admin/scraping/callback -> Supabase")
                return True
            else:
                print("  FAIL: Insert returned no data")
                return False

        except Exception as e:
            error_msg = str(e)
            print(f"  FAIL: Could not insert test record")
            print(f"  Error: {error_msg}")

            if "permission" in error_msg.lower() or "auth" in error_msg.lower():
                print("\n  NOTE: Anon key has limited permissions")
                print("  Callback API uses service role key for writes")
                print("  This is by design for security")

            return False

    return asyncio.run(run_test())


if __name__ == "__main__":
    result = test_supabase_writes()
    sys.exit(0 if result else 1)
