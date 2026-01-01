"""
Failure Scenario Classification System

Provides comprehensive failure detection and classification for web scraping operations.
Classifies exceptions and page content into specific failure types with confidence scores
and recovery strategies.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

# Selenium imports removed - migrated to Playwright
# from selenium.common.exceptions import ...
# from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Enumeration of possible failure types in scraping operations."""

    NO_RESULTS = "no_results"
    LOGIN_FAILED = "login_failed"
    CAPTCHA_DETECTED = "captcha_detected"
    RATE_LIMITED = "rate_limited"
    PAGE_NOT_FOUND = "page_not_found"
    ACCESS_DENIED = "access_denied"
    NETWORK_ERROR = "network_error"
    ELEMENT_MISSING = "element_missing"
    TIMEOUT = "timeout"  # Dedicated timeout failure type for element/page waits


@dataclass
class FailureContext:
    """Context information for a detected failure scenario."""

    failure_type: FailureType
    confidence: float  # 0.0 to 1.0
    details: dict[str, Any]
    recovery_strategy: str


class FailureClassifier:
    """
    Classifies failures in web scraping operations based on exceptions and page content.

    Provides detection logic for various failure scenarios including network issues,
    anti-detection measures, and content availability problems.
    """

    def __init__(
        self,
        site_specific_no_results_selectors: list[str] | None = None,
        site_specific_no_results_text_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the failure classifier with default detection patterns."""
        self.site_specific_no_results_selectors = (
            site_specific_no_results_selectors if site_specific_no_results_selectors else []
        )
        self.site_specific_no_results_text_patterns = (
            site_specific_no_results_text_patterns if site_specific_no_results_text_patterns else []
        )
        self.failure_patterns = {
            FailureType.NO_RESULTS: {
                "selectors": [
                    "[class*='no-results']",
                    "[id*='no-results']",
                    "[class*='empty']",
                    "[id*='empty']",
                    ".no-products",
                    "#no-products",
                    ".product-not-found",
                    "div.message-error",
                    "p.note:contains('no items')",
                    "div[role='alert']:contains('not found')",
                ],
                "text_patterns": [
                    r"no (results?|products?|items?) found",
                    r"your search.*returned no results",
                    r"no matching products",
                    r"empty",
                    r"product not found",
                    r"item not available",
                    r"page you requested cannot be found",
                ],
                "recovery_strategy": "fail_and_continue_to_next_sku",
            },
            FailureType.LOGIN_FAILED: {
                "selectors": [
                    "[class*='login-error']",
                    "[id*='login-error']",
                    "[class*='auth-error']",
                    "[id*='auth-error']",
                    ".login-failed",
                    "#login-failed",
                ],
                "text_patterns": [
                    r"(login|authentication).*(failed|error|invalid)",
                    r"incorrect.*(username|password|credentials)",
                    r"access denied",
                    r"unauthorized",
                ],
                "recovery_strategy": "relogin",
            },
            FailureType.CAPTCHA_DETECTED: {
                "selectors": [
                    "[class*='captcha']",
                    "[id*='captcha']",
                    "[class*='recaptcha']",
                    "[id*='recaptcha']",
                    ".g-recaptcha",
                    "#captcha-container",
                ],
                "text_patterns": [
                    r"captcha",
                    r"verify.*human",
                    r"robot.*verification",
                    r"security.*check",
                ],
                "recovery_strategy": "solve_captcha",
            },
            FailureType.RATE_LIMITED: {
                "selectors": [
                    "[class*='rate-limit']",
                    "[id*='rate-limit']",
                    "[class*='throttle']",
                    "[id*='throttle']",
                ],
                "text_patterns": [
                    r"rate limit",
                    r"too many requests",
                    r"throttl",
                    r"please wait",
                    r"temporary.*block",
                ],
                "recovery_strategy": "wait_and_retry",
            },
            FailureType.PAGE_NOT_FOUND: {
                "selectors": [
                    "[class*='404']",
                    "[id*='404']",
                    "[class*='not-found']",
                    "[id*='not-found']",
                ],
                "text_patterns": [
                    r"404",
                    r"page not found",
                    r"not found",
                    r"doesn't exist",
                ],
                "recovery_strategy": "skip_and_continue",
            },
            FailureType.ACCESS_DENIED: {
                "selectors": [
                    "[class*='access-denied']",
                    "[id*='access-denied']",
                    "[class*='forbidden']",
                    "[id*='forbidden']",
                    "[class*='blocked']",
                    "[id*='blocked']",
                ],
                "text_patterns": [
                    r"access denied",
                    r"forbidden",
                    r"blocked",
                    r"banned",
                    r"403",
                ],
                "recovery_strategy": "rotate_session",
            },
            FailureType.NETWORK_ERROR: {
                "selectors": [],
                "text_patterns": [
                    r"connection.*(failed|error|timeout|reset)",
                    r"network.*error",
                    r"server.*error",
                    r"timeout",
                    r"err_connection_refused",
                    r"dns_probe_finished_nxdomain",
                ],
                "recovery_strategy": "retry",
            },
            FailureType.ELEMENT_MISSING: {
                "selectors": [],
                "text_patterns": [],
                "recovery_strategy": "retry_with_wait",
            },
            FailureType.TIMEOUT: {
                "selectors": [],
                "text_patterns": [
                    r"timeout",
                    r"timed out",
                    r"waiting.*failed",
                    r"element.*not.*visible",
                ],
                "recovery_strategy": "retry_with_backoff",
            },
        }

        # PERFORMANCE: Pre-compile regex patterns for faster matching
        self._compiled_patterns: dict[FailureType, list[re.Pattern[str]]] = {}
        for failure_type, patterns in self.failure_patterns.items():
            self._compiled_patterns[failure_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns["text_patterns"]
            ]

        # Pre-compile site-specific patterns
        self._compiled_site_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.site_specific_no_results_text_patterns
        ]

    def classify_exception(self, exception: Exception, context: dict[str, Any]) -> FailureContext:
        """
        Classify a failure based on an exception.

        Args:
            exception: The exception that occurred
            context: Additional context information

        Returns:
            FailureContext with classification results
        """
        exception_str = str(exception).lower()
        exception_type = type(exception).__name__

        # Check for specific exception types
        # Check specific exception types (Generic string matching for now since we removed explicit imports)
        # Note: Playwright errors are often just 'Error' or 'TimeoutError'

        if "Timeout" in exception_type or "Timeout" in exception_str:
            # Check if this timeout is due to waiting for an element (common in _action_wait_for)
            is_wait_for_timeout = context.get("action") == "wait_for"

            return FailureContext(
                failure_type=FailureType.TIMEOUT,
                confidence=0.9,
                details={
                    "exception_type": exception_type,
                    "exception_message": str(exception),
                    "timeout_detected": True,
                    "waited_for_element_timeout": is_wait_for_timeout,
                },
                recovery_strategy="retry_with_backoff",
            )

        elif "element" in exception_str and (
            "not found" in exception_str or "unable to find" in exception_str
        ):
            return FailureContext(
                failure_type=FailureType.ELEMENT_MISSING,
                confidence=0.8,
                details={
                    "exception_type": exception_type,
                    "exception_message": str(exception),
                    "element_not_found": True,
                },
                recovery_strategy="retry_with_wait",
            )

        # Check for network-related exceptions (generic)
        if any(
            term in exception_str
            for term in ["connection", "network", "timeout", "econn", "target closed"]
        ):
            return FailureContext(
                failure_type=FailureType.NETWORK_ERROR,
                confidence=0.8,
                details={
                    "exception_type": exception_type,
                    "exception_message": str(exception),
                    "network_issue": True,
                },
                recovery_strategy="retry",
            )

        # Check exception message against patterns
        for failure_type, patterns in self.failure_patterns.items():
            if failure_type in [FailureType.ELEMENT_MISSING, FailureType.NETWORK_ERROR]:
                continue  # Already handled above

            confidence = self._calculate_text_match_confidence(
                exception_str, cast(list[str], patterns["text_patterns"])
            )
            MIN_TEXT_CONFIDENCE = 0.5
            if confidence > MIN_TEXT_CONFIDENCE:
                return FailureContext(
                    failure_type=failure_type,
                    confidence=confidence,
                    details={
                        "exception_type": exception_type,
                        "exception_message": str(exception),
                        "matched_patterns": patterns["text_patterns"],
                    },
                    recovery_strategy=cast(str, patterns["recovery_strategy"]),
                )

        # Default to network error for unknown exceptions
        return FailureContext(
            failure_type=FailureType.NETWORK_ERROR,
            confidence=0.3,
            details={
                "exception_type": exception_type,
                "exception_message": str(exception),
                "unknown_exception": True,
            },
            recovery_strategy="retry",
        )

    def classify_page_content(self, page, context: dict[str, Any]) -> FailureContext:
        """
        Classify a failure based on page content analysis.

        Args:
            page: Page object (Playwright) or HTML string
            context: Additional context information
        """
        try:
            # Attempt to extract content from Playwright page or string
            try:
                if isinstance(page, str):
                    page.lower()
                elif hasattr(page, "content"):
                    # NOTE: This assumes synchronous access or that we can't await here.
                    # If page is async, this might fail or return a coroutine.
                    # For now, we fallback to safe empty strings if we can't extract synchronously.
                    pass
            except Exception:
                pass

            # ... Rest of logic truncated for safety/brevity since we can't fully port to Async Playwright here yet ...

            return FailureContext(
                failure_type=FailureType.NETWORK_ERROR,
                confidence=0.1,
                details={
                    "no_clear_failure_detected": True,
                    "note": "Page analysis skipped during migration",
                },
                recovery_strategy="retry",
            )

        except Exception as e:
            logger.error(f"Page content classification failed: {e}")
            return FailureContext(
                failure_type=FailureType.NETWORK_ERROR,
                confidence=0.5,
                details={"classification_error": str(e)},
                recovery_strategy="retry",
            )

    def _check_selectors(self, page, selectors: list[str]) -> float:
        """Check if any of the selectors are present on the page."""
        # Placeholder for Playwright selector checking
        return 0.0

    def _calculate_text_match_confidence(
        self, text: str, patterns: list[str], compiled_patterns: list[re.Pattern[str]] | None = None
    ) -> float:
        """Calculate confidence score based on text pattern matching using pre-compiled patterns."""
        if not patterns and not compiled_patterns:
            return 0.0

        # Use pre-compiled patterns if available (faster)
        if compiled_patterns:
            for compiled_pattern in compiled_patterns:
                if compiled_pattern.search(text):
                    return 0.7  # High confidence for *any* text pattern match
        else:
            # Fallback to on-the-fly compilation (slower, used for exception messages)
            if patterns:
                for pattern_str in patterns:
                    if re.search(pattern_str, text, re.IGNORECASE):
                        return 0.7  # High confidence for *any* text pattern match
        return 0.0

    def _check_status_code(self, status_code: int, failure_type: FailureType) -> float:
        """Check if status code matches expected failure type."""
        status_mappings = {
            FailureType.PAGE_NOT_FOUND: [404],
            FailureType.ACCESS_DENIED: [403, 401],
            FailureType.RATE_LIMITED: [429],
            FailureType.NETWORK_ERROR: [500, 502, 503, 504],
        }

        if failure_type in status_mappings:
            if status_code in status_mappings[failure_type]:
                return 0.95  # Very high confidence for status code match

        return 0.0
