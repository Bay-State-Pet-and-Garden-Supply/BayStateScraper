"""
SKU Result Model and Pass/Fail Logic

This module provides the central source of truth for SKU status determination.
Both backend processing and health calculation should use these helpers.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from typing import Literal


# Valid SKU types
SkuType = Literal["test", "fake"]

# Valid outcomes from scraping
SkuOutcome = Literal["success", "no_results", "not_found", "error"]

# Health statuses
HealthStatus = Literal["healthy", "degraded", "broken", "unknown"]


def calculate_is_passing(sku_type: SkuType, outcome: SkuOutcome) -> bool:
    """
    Central logic for determining if a SKU result is passing.
    
    Test SKUs (real products we expect to find):
      - success → PASS (found the product)
      - no_results → FAIL (should have found data)
      - not_found → FAIL (couldn't find it)
      - error → FAIL (scraper error)
    
    Fake SKUs (products we expect NOT to find):
      - no_results → PASS (correctly detected empty page)
      - success → FAIL (shouldn't find data for fake SKU!)
      - not_found → FAIL (should detect no_results explicitly)
      - error → FAIL (scraper error)
    
    Args:
        sku_type: "test" for real products, "fake" for validation SKUs
        outcome: The result of the scraping attempt
        
    Returns:
        True if this result is considered passing, False otherwise
    """
    if sku_type == "fake":
        return outcome == "no_results"
    else:  # test
        return outcome == "success"


@dataclass
class SkuResult:
    """
    Structured result for a single SKU scrape attempt.
    
    Attributes:
        sku: The SKU identifier
        sku_type: "test" for real products, "fake" for validation SKUs
        outcome: The result of the scrape attempt
        is_passing: Pre-calculated pass/fail based on type + outcome
        data: Extracted product data (if any)
        error: Error message (if any)
        duration_seconds: How long the scrape took
    """
    sku: str
    sku_type: SkuType
    outcome: SkuOutcome
    is_passing: bool = field(init=False)
    data: dict | None = None
    error: str | None = None
    duration_seconds: float | None = None
    
    def __post_init__(self):
        """Calculate is_passing based on sku_type and outcome."""
        self.is_passing = calculate_is_passing(self.sku_type, self.outcome)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "sku": self.sku,
            "sku_type": self.sku_type,
            "outcome": self.outcome,
            "is_passing": self.is_passing,
            "data": self.data,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }


def calculate_health(results: list[SkuResult], config_has_fake_skus: bool = True) -> HealthStatus:
    """
    Calculate overall health status from a list of SKU results.
    
    Health Criteria:
    - "healthy": Has both test and fake SKUs, all passing
    - "degraded": Some passing but missing coverage OR has failures
    - "broken": All or most failing
    - "unknown": No results to evaluate
    
    Args:
        results: List of SkuResult objects
        config_has_fake_skus: Whether the scraper config includes fake SKUs
        
    Returns:
        Health status string
    """
    if not results:
        return "unknown"
    
    test_results = [r for r in results if r.sku_type == "test"]
    fake_results = [r for r in results if r.sku_type == "fake"]
    
    # Count passing results
    test_passing = sum(1 for r in test_results if r.is_passing)
    fake_passing = sum(1 for r in fake_results if r.is_passing)
    
    # Check if we have coverage
    has_test_coverage = len(test_results) > 0
    has_fake_coverage = len(fake_results) > 0
    
    # All tests pass?
    all_tests_pass = test_passing == len(test_results) if test_results else True
    all_fakes_pass = fake_passing == len(fake_results) if fake_results else True
    
    # Determine health
    if has_test_coverage and has_fake_coverage and all_tests_pass and all_fakes_pass:
        # Full coverage, all passing
        return "healthy"
    elif has_test_coverage and all_tests_pass and not config_has_fake_skus:
        # No fake SKUs configured, but all tests pass - still healthy
        return "healthy"
    elif all_tests_pass and all_fakes_pass:
        # Some passing but missing coverage (e.g., no fake SKUs tested)
        return "degraded"
    elif test_passing == 0 and fake_passing == 0:
        # Nothing passing
        return "broken"
    else:
        # Some failures
        return "degraded"


def summarize_results(results: list[SkuResult]) -> dict:
    """
    Create a summary of SKU results for reporting.
    
    Returns:
        Dictionary with counts and pass rates
    """
    test_results = [r for r in results if r.sku_type == "test"]
    fake_results = [r for r in results if r.sku_type == "fake"]
    
    return {
        "total": len(results),
        "test_skus": {
            "total": len(test_results),
            "passing": sum(1 for r in test_results if r.is_passing),
            "failing": sum(1 for r in test_results if not r.is_passing),
        },
        "fake_skus": {
            "total": len(fake_results),
            "passing": sum(1 for r in fake_results if r.is_passing),
            "failing": sum(1 for r in fake_results if not r.is_passing),
        },
        "outcomes": {
            "success": sum(1 for r in results if r.outcome == "success"),
            "no_results": sum(1 for r in results if r.outcome == "no_results"),
            "not_found": sum(1 for r in results if r.outcome == "not_found"),
            "error": sum(1 for r in results if r.outcome == "error"),
        },
    }
