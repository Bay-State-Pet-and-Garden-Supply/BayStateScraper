#!/usr/bin/env python3
"""
BayStateScraper - Development Test Script

Tests that the scraper runner is properly configured and can:
1. Load configuration
2. Connect to the API (health check)
3. Parse scraper configurations

Usage:
    python test_setup.py
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.chdir(project_root)

# Load .env file if present
from dotenv import load_dotenv

load_dotenv()


def test_python_version():
    """Test Python version compatibility."""
    print("[Python Version]")

    version = sys.version_info
    if version >= (3, 9):
        print(f"  OK: Python {version.major}.{version.minor}.{version.micro} (compatible)")
        return True
    else:
        print(f"  FAIL: Python {version.major}.{version.minor} (need 3.9+)")
        return False


def test_dependencies():
    """Test that all required dependencies are installed."""
    print("\n[Dependencies]")

    required = [
        ("httpx", "httpx"),
        ("playwright", "playwright"),
        ("pyyaml", "yaml"),  # PyYAML package imports as 'yaml'
        ("pydantic", "pydantic"),
        ("rich", "rich"),
        ("structlog", "structlog"),
        ("supabase", "supabase"),
    ]

    all_ok = True
    for package, import_name in required:
        try:
            __import__(import_name)
            print(f"  OK: {package}")
        except ImportError:
            print(f"  FAIL: {package} (missing)")
            all_ok = False

    return all_ok


def test_api_client():
    """Test API client configuration."""
    print("\n[API Configuration]")

    from core.api_client import ScraperAPIClient

    api_url = os.environ.get("SCRAPER_API_URL", "")
    api_key = os.environ.get("SCRAPER_API_KEY", "")

    if not api_url:
        print("  WARN: SCRAPER_API_URL not set")
        return False

    print(f"  OK: SCRAPER_API_URL: {api_url}")

    if not api_key:
        print("  WARN: SCRAPER_API_KEY not set")
        return False

    print(f"  OK: SCRAPER_API_KEY: {api_key[:10]}...")

    return True


def test_health_check():
    """Test API health check (optional - may fail if API is unreachable)."""
    print("\n[API Health Check]")

    from core.api_client import ScraperAPIClient, ConnectionError

    api_url = os.environ.get("SCRAPER_API_URL", "")

    if not api_url:
        print("  SKIP: No API URL configured")
        return True

    client = ScraperAPIClient()

    try:
        health = client.health_check()
        if health:
            print("  OK: API is healthy")
            return True
        else:
            print("  FAIL: API health check returned False")
            return False
    except ConnectionError as e:
        print(f"  WARN: Connection failed: {e}")
        print("     This is expected if the API is unreachable")
        return True  # Don't fail the test for this
    except Exception as e:
        print(f"  FAIL: Health check failed: {e}")
        return False


def test_config_parsing():
    """Test scraper configuration parsing."""
    print("\n[Config Parsing]")

    from scrapers.parser import ScraperConfigParser

    # Test with a minimal valid config (selectors must be a list, not dict)
    test_config = {
        "name": "test-scraper",
        "base_url": "https://example.com",
        "selectors": [
            {
                "name": "product_title",
                "selector": "h1.title",
                "attribute": "text",
            }
        ],
    }

    try:
        parser = ScraperConfigParser()
        config = parser.load_from_dict(test_config)
        print(f"  OK: Parsed config: {config.name}")
        return True
    except Exception as e:
        print(f"  FAIL: Config parsing failed: {e}")
        return False


def main():
    print("=" * 60)
    print("BayStateScraper - Development Setup Test")
    print("=" * 60)

    tests = [
        ("Python Version", test_python_version),
        ("Dependencies", test_dependencies),
        ("API Configuration", test_api_client),
        ("Config Parsing", test_config_parsing),
        ("API Health Check", test_health_check),
    ]

    results = []
    for name, test_fn in tests:
        try:
            results.append((name, test_fn()))
        except Exception as e:
            print(f"  FAIL: {name} failed with error: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("[Summary]")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {status}: {name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\nOK: All tests passed! BayStateScraper is ready for development.")
        return 0
    else:
        print("\nWARN: Some tests failed. Review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
