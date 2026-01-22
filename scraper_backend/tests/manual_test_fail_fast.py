#!/usr/bin/env python
"""
Manual test script to demonstrate fail-fast behavior with invalid config.

This script tests the config fetcher's ability to:
1. Fail fast on invalid configs
2. Provide clear error messages with slug and schema_version
3. Not continue with invalid configs
"""

from unittest.mock import MagicMock

from scraper_backend.core.config_fetcher import (
    fetch_and_validate_config,
    ConfigFetchError,
    ConfigValidationError,
)


def test_invalid_config_fails_fast():
    """Test that invalid config causes immediate failure."""
    print("=" * 60)
    print("TEST: Invalid config fails fast")
    print("=" * 60)

    mock_client = MagicMock()
    mock_client._make_request.return_value = {
        "schema_version": "1.0",
        "slug": "test-scraper",
        "version_number": 1,
        "status": "published",
        "config": {
            "schema_version": "1.0",
            # Missing required fields: name, base_url
        },
        "published_at": "2026-01-22T10:00:00Z",
        "published_by": "user-123",
    }

    try:
        fetch_and_validate_config(mock_client, "test-scraper")
        print("FAIL: Expected ConfigValidationError was not raised!")
        return False
    except ConfigValidationError as e:
        print(f"SUCCESS: ConfigValidationError raised as expected")
        print(f"  - Config slug: {e.config_slug}")
        print(f"  - Schema version: {e.schema_version}")
        print(f"  - Validation errors: {len(e.validation_errors)}")
        print(f"  - Error message: {e}")

        # Verify error message includes slug and version
        assert "test-scraper" in str(e), "Error should include slug"
        assert "1.0" in str(e), "Error should include schema_version"
        print("SUCCESS: Error message includes slug and schema_version")
        return True


def test_unknown_schema_version_fails():
    """Test that unknown schema_version is rejected."""
    print("\n" + "=" * 60)
    print("TEST: Unknown schema_version fails")
    print("=" * 60)

    mock_client = MagicMock()
    mock_client._make_request.return_value = {
        "schema_version": "1.0",
        "slug": "test-scraper",
        "version_number": 1,
        "status": "published",
        "config": {
            "schema_version": "99.0",  # Unknown version
            "name": "test",
            "base_url": "https://example.com",
        },
        "published_at": "2026-01-22T10:00:00Z",
        "published_by": "user-123",
    }

    try:
        fetch_and_validate_config(mock_client, "test-scraper")
        print("FAIL: Expected ConfigValidationError was not raised!")
        return False
    except ConfigValidationError as e:
        print(f"SUCCESS: ConfigValidationError raised for unknown schema_version")
        print(f"  - Error: {e}")
        return True


def test_api_error_fails_fast():
    """Test that API errors fail fast without continuing."""
    print("\n" + "=" * 60)
    print("TEST: API error fails fast")
    print("=" * 60)

    mock_client = MagicMock()
    mock_client._make_request.side_effect = Exception("Connection refused")

    try:
        fetch_and_validate_config(mock_client, "test-scraper")
        print("FAIL: Expected ConfigFetchError was not raised!")
        return False
    except ConfigFetchError as e:
        print(f"SUCCESS: ConfigFetchError raised as expected")
        print(f"  - Config slug: {e.config_slug}")
        print(f"  - Error message: {e}")
        assert e.config_slug == "test-scraper", "Error should include slug"
        print("SUCCESS: Error includes slug from parameter")
        return True


def main():
    """Run all tests."""
    print("\n" + "#" * 60)
    print("# Config Fetcher Fail-Fast Behavior Tests")
    print("#" * 60 + "\n")

    results = []

    results.append(("Invalid config fails fast", test_invalid_config_fails_fast()))
    results.append(
        ("Unknown schema_version fails", test_unknown_schema_version_fails())
    )
    results.append(("API error fails fast", test_api_error_fails_fast()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == "__main__":
    exit(main())
