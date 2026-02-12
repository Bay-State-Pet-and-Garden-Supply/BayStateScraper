"""
Retry Executor with Circuit Breaker Pattern

Provides intelligent retry logic for scraper actions with:
- Adaptive retry configuration based on failure history
- Circuit breaker pattern to prevent cascading failures
- Integration with failure analytics for learning
- Configurable backoff strategies
"""

from __future__ import annotations


import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from core.adaptive_retry_strategy import (
    AdaptiveRetryConfig,
    AdaptiveRetryStrategy,
    RetryStrategy,
)
from core.adaptive_retry_strategy import FailureContext as AdaptiveFailureContext
from core.failure_analytics import FailureAnalytics
from core.failure_classifier import FailureClassifier, FailureType

# Import directly from exceptions module to avoid circular import
# (scrapers.__init__ -> executor -> retry_executor -> scrapers.exceptions)
from scrapers.exceptions import (
    AccessDeniedError,
    CaptchaError,
    CircuitBreakerOpenError,
    ErrorContext,
    MaxRetriesExceededError,
    NonRetryableError,
    RateLimitError,
    RetryableError,
    ScraperError,
    classify_exception,
    is_retryable,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Failures exceeded threshold, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5  # Failures before opening circuit
    success_threshold: int = 2  # Successes needed to close circuit
    timeout_seconds: float = 60.0  # Time before trying half-open
    half_open_max_calls: int = 3  # Max calls in half-open state


@dataclass
class CircuitBreakerState:
    """State tracking for circuit breaker."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    half_open_calls: int = 0


@dataclass
class RetryResult:
    """Result of a retry operation."""

    success: bool
    result: Any = None
    error: Exception | None = None
    attempts: int = 0
    total_delay: float = 0.0
    final_failure_type: FailureType | None = None
    cancelled: bool = False


class RetryExecutor:
    """
    Executes operations with intelligent retry logic and circuit breaker protection.

    Features:
    - Adaptive retry configuration based on site/failure history
    - Circuit breaker pattern per site
    - Exponential backoff with jitter
    - Integration with failure analytics
    - Recovery action hooks (CAPTCHA solving, session rotation)
    """

    def __init__(
        self,
        adaptive_strategy: AdaptiveRetryStrategy | None = None,
        failure_analytics: FailureAnalytics | None = None,
        failure_classifier: FailureClassifier | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ) -> None:
        """
        Initialize the retry executor.

        Args:
            adaptive_strategy: Strategy for adaptive retry configuration
            failure_analytics: Analytics system for recording failures
            failure_classifier: Classifier for determining failure types
            circuit_breaker_config: Configuration for circuit breaker
        """
        self.adaptive_strategy = adaptive_strategy or AdaptiveRetryStrategy()
        self.failure_analytics = failure_analytics or FailureAnalytics()
        self.failure_classifier = failure_classifier or FailureClassifier()
        self.circuit_config = circuit_breaker_config or CircuitBreakerConfig()

        # Per-site circuit breaker states
        self._circuit_states: dict[str, CircuitBreakerState] = {}
        self._lock = threading.RLock()

        # Recovery action callbacks
        self._recovery_handlers: dict[FailureType, Callable[..., bool]] = {}

    def register_recovery_handler(self, failure_type: FailureType, handler: Callable[..., bool]) -> None:
        """
        Register a recovery handler for a specific failure type.

        Args:
            failure_type: The failure type to handle
            handler: Callable that attempts recovery, returns True if successful
        """
        self._recovery_handlers[failure_type] = handler
        logger.info(f"Registered recovery handler for {failure_type.value}")

    async def execute_with_retry(
        self,
        operation: Callable[[], T],
        site_name: str,
        action_name: str,
        context: ErrorContext | None = None,
        max_retries: int | None = None,
        base_delay: float | None = None,
        on_retry: Callable[[int, Exception, float], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> RetryResult:
        """
        Execute an operation with retry logic.

        Args:
            operation: The operation to execute
            site_name: Name of the site being scraped
            action_name: Name of the action being performed
            context: Error context for debugging
            max_retries: Override max retries (uses adaptive config if None)
            base_delay: Override base delay (uses adaptive config if None)
            on_retry: Optional callback called before each retry (attempt, error, delay)
            stop_event: Optional threading.Event to check for cancellation

        Returns:
            RetryResult with success status and details
        """
        ctx = context or ErrorContext(site_name=site_name, action=action_name)
        ctx.site_name = site_name
        ctx.action = action_name

        # Check circuit breaker
        if not self._check_circuit_breaker(site_name):
            logger.warning(f"Circuit breaker OPEN for {site_name}, blocking request")
            return RetryResult(
                success=False,
                error=CircuitBreakerOpenError(f"Circuit breaker open for {site_name}", context=ctx),
                attempts=0,
            )

        attempt = 0
        total_delay = 0.0
        last_error: Exception | None = None
        last_failure_type: FailureType | None = None

        # Get adaptive config for initial settings
        config = self.adaptive_strategy.get_adaptive_config(
            FailureType.NETWORK_ERROR,  # Default type, will be updated
            site_name,
            current_retry_count=0,
        )

        effective_max_retries = max_retries if max_retries is not None else config.max_retries
        effective_base_delay = base_delay if base_delay is not None else config.base_delay

        ctx.max_retries = effective_max_retries

        while attempt <= effective_max_retries:
            ctx.retry_count = attempt

            start_time = time.time()
            try:
                # Execute the operation
                import inspect

                op_result = operation()
                if inspect.isawaitable(op_result):
                    result = await op_result
                else:
                    result = op_result
                duration = time.time() - start_time

                # Success! Record and return
                self._record_success(site_name, action_name, duration)
                self._update_circuit_breaker_success(site_name)

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                )

            except Exception as exc:
                duration = time.time() - start_time

                # Classify the exception
                scraper_error = classify_exception(exc, ctx)
                last_error = scraper_error
                last_failure_type = self._map_to_failure_type(scraper_error)

                logger.warning(f"Attempt {attempt + 1}/{effective_max_retries + 1} failed for {site_name}/{action_name}: {scraper_error.message}")

                # Record failure
                self._record_failure(
                    site_name,
                    action_name,
                    last_failure_type,
                    attempt,
                    duration,
                    ctx,
                )

                # Check if we should retry
                if not is_retryable(scraper_error):
                    logger.info(f"Non-retryable error, stopping: {type(scraper_error).__name__}")
                    self._update_circuit_breaker_failure(site_name)
                    return RetryResult(
                        success=False,
                        error=scraper_error,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        final_failure_type=last_failure_type,
                    )

                # Check if we've exhausted retries
                if attempt >= effective_max_retries:
                    logger.error(f"Max retries ({effective_max_retries}) exceeded for {action_name}")
                    self._update_circuit_breaker_failure(site_name)
                    return RetryResult(
                        success=False,
                        error=MaxRetriesExceededError(
                            f"Max retries exceeded: {scraper_error.message}",
                            context=ctx,
                            cause=scraper_error,
                        ),
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        final_failure_type=last_failure_type,
                    )

                # Try recovery action if available
                if last_failure_type in self._recovery_handlers:
                    logger.info(f"Attempting recovery for {last_failure_type.value}")
                    try:
                        if self._recovery_handlers[last_failure_type](ctx):
                            logger.info("Recovery successful, retrying operation")
                            # Don't increment attempt after successful recovery
                            continue
                    except Exception as recovery_exc:
                        logger.warning(f"Recovery failed: {recovery_exc}")

                # Calculate delay with adaptive config
                config = self.adaptive_strategy.get_adaptive_config(last_failure_type, site_name, attempt)
                delay = self._calculate_delay(config, attempt, effective_base_delay, last_failure_type)

                # Add jitter to prevent thundering herd
                import random

                jitter = delay * 0.1 * random.random()
                delay += jitter

                total_delay += delay

                # Notify callback if provided
                if on_retry:
                    try:
                        on_retry(attempt, scraper_error, delay)
                    except Exception as cb_err:
                        logger.debug(f"Retry callback error (ignored): {cb_err}")

                # Check for cancellation before retry delay
                if stop_event and stop_event.is_set():
                    logger.warning(f"Retry cancelled for {site_name}/{action_name} after {attempt + 1} attempts")
                    return RetryResult(
                        success=False,
                        error=last_error,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        final_failure_type=last_failure_type,
                        cancelled=True,
                    )

                logger.info(f"Waiting {delay:.2f}s before retry {attempt + 2}")
                time.sleep(delay)

                attempt += 1

        # Should not reach here, but just in case
        return RetryResult(
            success=False,
            error=last_error,
            attempts=attempt,
            total_delay=total_delay,
            final_failure_type=last_failure_type,
        )

    def _calculate_delay(
        self,
        config: AdaptiveRetryConfig,
        attempt: int,
        base_delay: float,
        failure_type: FailureType | None,
    ) -> float:
        """Calculate delay for retry with strategy-specific logic."""
        delay = self.adaptive_strategy.calculate_delay(config, attempt)

        # Apply minimum delays for specific failure types
        if failure_type == FailureType.RATE_LIMITED:
            delay = max(delay, 10.0)  # At least 10s for rate limits
        elif failure_type == FailureType.CAPTCHA_DETECTED:
            delay = max(delay, 5.0)  # At least 5s for CAPTCHA
        elif failure_type == FailureType.ACCESS_DENIED:
            delay = max(delay, 15.0)  # At least 15s for access denied

        return delay

    def _map_to_failure_type(self, error: ScraperError) -> FailureType:
        """Map ScraperError to FailureType for analytics."""
        mapping = {
            RateLimitError: FailureType.RATE_LIMITED,
            CaptchaError: FailureType.CAPTCHA_DETECTED,
            AccessDeniedError: FailureType.ACCESS_DENIED,
        }

        for error_class, failure_type in mapping.items():
            if isinstance(error, error_class):
                return failure_type

        # Check error message for patterns
        error_str = str(error).lower()
        if "element" in error_str:
            return FailureType.ELEMENT_MISSING
        if "login" in error_str or "auth" in error_str:
            return FailureType.LOGIN_FAILED
        if "no results" in error_str or "not found" in error_str:
            return FailureType.NO_RESULTS

        return FailureType.NETWORK_ERROR

    def _record_success(self, site_name: str, action: str, duration: float) -> None:
        """Record successful operation."""
        self.failure_analytics.record_success(
            site_name=site_name,
            duration=duration,
            action=action,
        )

    def _record_failure(
        self,
        site_name: str,
        action: str,
        failure_type: FailureType,
        retry_count: int,
        duration: float,
        context: ErrorContext,
    ) -> None:
        """Record failed operation."""
        self.failure_analytics.record_failure(
            site_name=site_name,
            failure_type=failure_type,
            duration=duration,
            action=action,
            retry_count=retry_count,
            context=context.to_dict(),
        )

        # Also record in adaptive strategy for learning
        adaptive_ctx = AdaptiveFailureContext(
            site_name=site_name,
            action=action,
            retry_count=retry_count,
            context=context.to_dict(),
            failure_type=failure_type,
        )
        self.adaptive_strategy.record_failure(adaptive_ctx)

    # Circuit Breaker Methods

    def _get_circuit_state(self, site_name: str) -> CircuitBreakerState:
        """Get or create circuit breaker state for a site."""
        with self._lock:
            if site_name not in self._circuit_states:
                self._circuit_states[site_name] = CircuitBreakerState()
            return self._circuit_states[site_name]

    def _check_circuit_breaker(self, site_name: str) -> bool:
        """
        Check if request should be allowed based on circuit breaker state.

        Returns:
            True if request is allowed, False if blocked
        """
        with self._lock:
            state = self._get_circuit_state(site_name)

            if state.state == CircuitState.CLOSED:
                return True

            if state.state == CircuitState.OPEN:
                # Check if timeout has passed
                if state.last_failure_time:
                    elapsed = time.time() - state.last_failure_time
                    if elapsed >= self.circuit_config.timeout_seconds:
                        logger.info(f"Circuit breaker transitioning to HALF_OPEN for {site_name}")
                        state.state = CircuitState.HALF_OPEN
                        state.half_open_calls = 0
                        return True
                return False

            if state.state == CircuitState.HALF_OPEN:
                # Allow limited calls in half-open state
                if state.half_open_calls < self.circuit_config.half_open_max_calls:
                    state.half_open_calls += 1
                    return True
                return False

            return True

    def _update_circuit_breaker_success(self, site_name: str) -> None:
        """Update circuit breaker on successful operation."""
        with self._lock:
            state = self._get_circuit_state(site_name)

            if state.state == CircuitState.HALF_OPEN:
                state.success_count += 1
                if state.success_count >= self.circuit_config.success_threshold:
                    logger.info(f"Circuit breaker CLOSED for {site_name} after recovery")
                    state.state = CircuitState.CLOSED
                    state.failure_count = 0
                    state.success_count = 0

            elif state.state == CircuitState.CLOSED:
                # Reset failure count on success
                state.failure_count = max(0, state.failure_count - 1)

    def _update_circuit_breaker_failure(self, site_name: str) -> None:
        """Update circuit breaker on failed operation."""
        with self._lock:
            state = self._get_circuit_state(site_name)
            state.failure_count += 1
            state.last_failure_time = time.time()

            if state.state == CircuitState.HALF_OPEN:
                # Failure in half-open state -> back to open
                logger.warning(f"Circuit breaker returning to OPEN for {site_name}")
                state.state = CircuitState.OPEN
                state.success_count = 0

            elif state.state == CircuitState.CLOSED:
                if state.failure_count >= self.circuit_config.failure_threshold:
                    logger.warning(f"Circuit breaker OPEN for {site_name} after {state.failure_count} failures")
                    state.state = CircuitState.OPEN

    def get_circuit_breaker_status(self, site_name: str) -> dict[str, Any]:
        """Get current circuit breaker status for a site."""
        with self._lock:
            state = self._get_circuit_state(site_name)
            return {
                "site": site_name,
                "state": state.state.value,
                "failure_count": state.failure_count,
                "success_count": state.success_count,
                "last_failure_time": state.last_failure_time,
            }

    def reset_circuit_breaker(self, site_name: str) -> None:
        """Manually reset circuit breaker for a site."""
        with self._lock:
            if site_name in self._circuit_states:
                self._circuit_states[site_name] = CircuitBreakerState()
                logger.info(f"Circuit breaker reset for {site_name}")
