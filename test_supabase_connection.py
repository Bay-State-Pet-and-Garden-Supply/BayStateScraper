#!/usr/bin/env python3
"""
Test Supabase Connection for BayStateScraper.

This script tests:
1. API connectivity and Supabase config retrieval
2. WebSocket connection to Supabase Realtime
3. Presence channel functionality

Usage:
    python test_supabase_connection.py
"""

import sys
import os

# Add project root to path
project_root = r"C:\Users\thoma\OneDrive\Desktop\scripts\BayState\BayStateScraper"
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.chdir(project_root)

# Load .env file
from dotenv import load_dotenv

load_dotenv()


def test_supabase():
    from core.api_client import ScraperAPIClient
    from core.realtime_manager import RealtimeManager
    import asyncio

    async def run_test():
        print("=" * 60)
        print("Testing Supabase Connection")
        print("=" * 60)

        # Initialize API client
        client = ScraperAPIClient()

        print(f"\nAPI URL: {client.api_url}")
        if client.api_key:
            print(f"API Key: {client.api_key[:10]}...")
        else:
            print("API Key: NOT SET")

        # Fetch Supabase config
        print("\n[1] Fetching Supabase config from API...")
        supabase_config = client.get_supabase_config()

        if not supabase_config:
            print("FAIL: Could not fetch Supabase config from API")
            print("This may mean the API endpoint /api/scraper/v1/supabase-config is not available")
            return False

        print(f"  Supabase URL: {supabase_config.get('supabase_url', 'N/A')}")
        rt_key = supabase_config.get("supabase_realtime_key", "")
        print(f"  Realtime Key: {rt_key[:20]}..." if rt_key else "  Realtime Key: NOT SET")

        # Test WebSocket connection
        supabase_url = supabase_config.get("supabase_url", "")
        if not supabase_url:
            print("FAIL: No Supabase URL in config")
            return False

        if supabase_url.startswith("https://"):
            ws_url = supabase_url.replace("https://", "wss://") + "/realtime/v1"
        elif supabase_url.startswith("http://"):
            ws_url = supabase_url.replace("http://", "ws://") + "/realtime/v1"
        else:
            ws_url = supabase_url

        print(f"\n[2] Connecting to Supabase Realtime WebSocket...")
        print(f"  WebSocket URL: {ws_url}")

        rm = RealtimeManager(ws_url, supabase_config["supabase_realtime_key"], "test-runner")

        try:
            connected = await rm.connect()
            if connected:
                print("  OK: WebSocket connection established")

                # Test presence
                print("\n[3] Testing presence channel...")
                presence_ok = await rm.enable_presence()
                if presence_ok:
                    print("  OK: Presence channel enabled")
                else:
                    print("  WARN: Could not enable presence channel")

                # Clean up
                await rm.disconnect()
                print("\n[4] Disconnected from Supabase")

                print("\n" + "=" * 60)
                print("SUCCESS: Supabase connection test passed!")
                print("=" * 60)
                return True
            else:
                print("FAIL: Could not connect to Supabase Realtime")
                return False
        except Exception as e:
            print(f"FAIL: Error during Supabase connection test: {e}")
            import traceback

            traceback.print_exc()
            return False

    return asyncio.run(run_test())


if __name__ == "__main__":
    result = test_supabase()
    sys.exit(0 if result else 1)
