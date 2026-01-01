"""
ProductScraper Core Module
Provides core functionality for scraping, data processing, and platform integration.
"""

from .failure_classifier import FailureClassifier, FailureContext, FailureType
from .scraper_testing_client import ScraperTestingClient, TestingMode

__all__ = [
    "FailureClassifier",
    "FailureContext",
    "FailureType",
    "ScraperTestingClient",
    "TestingMode",
]
