"""
Scraper Exception Hierarchy

Provides structured exceptions for different failure scenarios with context
for debugging and automatic recovery decisions.
"""

from __future__ import annotations


from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorSeverity(Enum):
    """Severity levels for scraper errors."""

    LOW = "low"  # Minor issue, can continue
    MEDIUM = "medium"  # Significant issue, may need retry
    HIGH = "high"  # Critical issue, likely need to stop
    CRITICAL = "critical"  # Fatal issue, must stop immediately


@dataclass
class ErrorContext:
    """Context information for debugging scraper errors."""

    site_name: str | None = None
    action: str | None = None
    step_index: int | None = None
    selector: str | None = None
    url: str | None = None
    sku: str | None = None
    retry_count: int = 0
    max_retries: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "site_name": self.site_name,
            "action": self.action,
            "step_index": self.step_index,
            "selector": self.selector,
            "url": self.url,
            "sku": self.sku,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            **self.extra,
        }


class ScraperError(Exception):
    """Base exception for all scraper errors with context support."""

    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retryable: bool = True

    def __init__(
        self,
        message: str,
        context: ErrorContext | None = None,
        cause: Exception | None = None,
    ):
        self.message = message
        self.context = context or ErrorContext()
        self.cause = cause
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format error message with context."""
        parts = [self.message]
        if self.context.site_name:
            parts.append(f"site={self.context.site_name}")
        if self.context.action:
            parts.append(f"action={self.context.action}")
        if self.context.sku:
            parts.append(f"sku={self.context.sku}")
        if self.context.retry_count > 0:
            parts.append(f"retry={self.context.retry_count}/{self.context.max_retries}")
        return " | ".join(parts)


class WorkflowExecutionError(ScraperError):
    """Exception raised during workflow execution."""

    severity = ErrorSeverity.MEDIUM
    retryable = True


# Retryable Errors (transient issues that may resolve on retry)


class RetryableError(ScraperError):
    """Base class for errors that should trigger a retry."""

    severity = ErrorSeverity.MEDIUM
    retryable = True


class NetworkError(RetryableError):
    """Network-related errors (timeout, connection issues)."""

    severity = ErrorSeverity.MEDIUM


class TimeoutError(RetryableError):
    """Operation timed out."""

    severity = ErrorSeverity.MEDIUM


class ElementNotFoundError(RetryableError):
    """Element not found on page (may appear after wait)."""

    severity = ErrorSeverity.LOW


class PageLoadError(RetryableError):
    """Page failed to load properly."""

    severity = ErrorSeverity.MEDIUM


class StaleElementError(RetryableError):
    """Element reference became stale."""

    severity = ErrorSeverity.LOW


# Rate Limiting & Anti-Bot Errors


class RateLimitError(RetryableError):
    """Rate limited by the target site."""

    severity = ErrorSeverity.HIGH
    # Retryable but needs longer delay


class CaptchaError(RetryableError):
    """CAPTCHA detected and needs solving."""

    severity = ErrorSeverity.HIGH


class AccessDeniedError(RetryableError):
    """Access denied (403, blocked IP, etc.)."""

    severity = ErrorSeverity.HIGH


class SessionExpiredError(RetryableError):
    """Session has expired and needs refresh."""

    severity = ErrorSeverity.MEDIUM


# Non-Retryable Errors (permanent issues that won't resolve on retry)


class NonRetryableError(ScraperError):
    """Base class for errors that should NOT trigger a retry."""

    severity = ErrorSeverity.HIGH
    retryable = False


class ConfigurationError(NonRetryableError):
    """Invalid scraper configuration."""

    severity = ErrorSeverity.CRITICAL


class SelectorError(NonRetryableError):
    """Invalid or broken selector in configuration."""

    severity = ErrorSeverity.HIGH


class AuthenticationError(NonRetryableError):
    """Login/authentication failed (bad credentials)."""

    severity = ErrorSeverity.HIGH


class PageNotFoundError(NonRetryableError):
    """Page/product does not exist (404)."""

    severity = ErrorSeverity.LOW
    # Not retryable, but not critical - just skip this SKU


class NoResultsError(NonRetryableError):
    """No results found for the search/SKU."""

    severity = ErrorSeverity.LOW
    # Not retryable - product doesn't exist on this site


class BrowserError(NonRetryableError):
    """Browser crashed or became unresponsive."""

    severity = ErrorSeverity.CRITICAL


# Circuit Breaker Errors


class CircuitBreakerOpenError(NonRetryableError):
    """Circuit breaker is open - too many failures."""

    severity = ErrorSeverity.CRITICAL
    retryable = False


class MaxRetriesExceededError(NonRetryableError):
    """Maximum retry attempts exceeded."""

    severity = ErrorSeverity.HIGH
    retryable = False


# Utility functions for exception handling


def classify_exception(
    exc: Exception,
    context: ErrorContext | None = None,
) -> ScraperError:
    """
    Classify a generic exception into the appropriate ScraperError type.

    Args:
        exc: The original exception
        context: Optional error context

    Returns:
        Appropriate ScraperError subclass instance
    """
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__
    ctx = context or ErrorContext()

    # Generic exception classification by type name and message
    if "Timeout" in exc_type or "timeout" in exc_str:
        return TimeoutError("Operation timed out", context=ctx, cause=exc)

    if "NoSuchElement" in exc_type or ("element" in exc_str and "not found" in exc_str):
        return ElementNotFoundError("Element not found", context=ctx, cause=exc)

    if "StaleElement" in exc_type or "stale" in exc_str:
        return StaleElementError("Element reference is stale", context=ctx, cause=exc)

    if "WebDriver" in exc_type or "browser" in exc_str:
        if "net::" in exc_str or "connection" in exc_str:
            return NetworkError("Network error", context=ctx, cause=exc)
        if "session" in exc_str and ("deleted" in exc_str or "invalid" in exc_str):
            return BrowserError("Browser session invalid", context=ctx, cause=exc)
        return PageLoadError("WebDriver error", context=ctx, cause=exc)

    # Pattern matching on error messages
    if any(term in exc_str for term in ["rate limit", "too many requests", "throttl"]):
        return RateLimitError("Rate limited", context=ctx, cause=exc)

    if any(term in exc_str for term in ["captcha", "recaptcha", "robot"]):
        return CaptchaError("CAPTCHA detected", context=ctx, cause=exc)

    if any(term in exc_str for term in ["403", "forbidden", "access denied", "blocked"]):
        return AccessDeniedError("Access denied", context=ctx, cause=exc)

    if any(term in exc_str for term in ["404", "not found"]):
        return PageNotFoundError("Page not found", context=ctx, cause=exc)

    if any(term in exc_str for term in ["no results", "no products", "empty"]):
        return NoResultsError("No results found", context=ctx, cause=exc)

    if any(term in exc_str for term in ["timeout", "timed out"]):
        return TimeoutError("Operation timed out", context=ctx, cause=exc)

    if any(term in exc_str for term in ["connection", "network", "dns"]):
        return NetworkError("Network error", context=ctx, cause=exc)

    # Default to retryable workflow error
    return WorkflowExecutionError(str(exc), context=ctx, cause=exc)


def is_retryable(exc: Exception) -> bool:
    """Check if an exception should trigger a retry."""
    if isinstance(exc, ScraperError):
        return exc.retryable
    # For unknown exceptions, check common patterns
    return classify_exception(exc).retryable
