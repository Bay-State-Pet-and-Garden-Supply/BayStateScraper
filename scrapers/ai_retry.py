"""
AI-Specific Retry Strategies for LLM API Operations

Extends AdaptiveRetryStrategy with specialized handling for AI service failures
including rate limits, context length errors, timeout patterns, and anti-bot detection.

Provides intelligent retry logic for OpenAI and other LLM APIs with circuit breaker
protection and adaptive backoff strategies.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from core.adaptive_retry_strategy import (
    AdaptiveRetryConfig,
    AdaptiveRetryStrategy,
    FailureContext,
    RetryStrategy,
)
from core.failure_classifier import FailureType
from scrapers.exceptions import (
    CircuitBreakerOpenError,
    MaxRetriesExceededError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AIFailureType(Enum):
    """Extended failure types specific to AI/LLM operations."""

    # Rate limiting patterns
    RATE_LIMIT_TIER1 = "rate_limit_tier1"  # Standard rate limit (requests/min)
    RATE_LIMIT_TIER2 = "rate_limit_tier2"  # Aggressive rate limit (tokens/min)
    RATE_LIMIT_TIER3 = "rate_limit_tier3"  # Hard limit (account level)

    # Context/token errors
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    TOKEN_LIMIT_EXCEEDED = "token_limit_exceeded"
    MAX_TOKENS_TOO_LOW = "max_tokens_too_low"

    # Model availability
    MODEL_OVERLOADED = "model_overloaded"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_DEPRECATED = "model_deprecated"

    # Content filtering
    CONTENT_FILTERED = "content_filtered"
    SAFETY_VIOLATION = "safety_violation"

    # API errors
    API_ERROR = "api_error"
    API_TIMEOUT = "api_timeout"
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION_ERROR = "authentication_error"

    # Anti-bot detection (AI services sometimes use these)
    ANTI_BOT_DETECTED = "anti_bot_detected"
    IP_BLOCKED = "ip_blocked"


@dataclass
class AICircuitBreakerConfig:
    """Configuration for AI-specific circuit breaker behavior."""

    # Standard circuit breaker settings
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60.0
    half_open_max_calls: int = 3

    # AI-specific settings
    rate_limit_open_duration: float = 60.0  # Longer timeout for rate limits
    model_overload_open_duration: float = 30.0  # Shorter for temporary overloads
    consecutive_rate_limit_threshold: int = 3  # Open after N consecutive rate limits


@dataclass
class AICircuitBreakerState:
    """State tracking for AI-specific circuit breaker."""

    state: str = "closed"  # "closed", "open", "half_open"
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    half_open_calls: int = 0
    consecutive_rate_limits: int = 0
    last_rate_limit_time: float | None = None


@dataclass
class AIRetryConfig:
    """Configuration for AI-specific retry behavior."""

    # Base delays for different failure types (in seconds)
    rate_limit_base_delay: float = 1.0
    rate_limit_max_delay: float = 60.0
    overload_base_delay: float = 2.0
    overload_max_delay: float = 30.0
    timeout_base_delay: float = 5.0
    timeout_max_delay: float = 60.0
    anti_bot_base_delay: float = 30.0
    anti_bot_max_delay: float = 300.0

    # Retry limits
    max_rate_limit_retries: int = 5
    max_overload_retries: int = 3
    max_timeout_retries: int = 3
    max_anti_bot_retries: int = 2

    # Adaptive settings
    enable_jitter: bool = True
    jitter_factor: float = 0.1
    exponential_base: float = 2.0

    # Context length handling
    auto_reduce_context: bool = True
    context_reduction_factor: float = 0.75
    min_context_tokens: int = 1000


@dataclass
class AIRetryContext:
    """Context for AI retry operations."""

    provider: str  # e.g., "openai", "anthropic", "google"
    model: str | None = None
    operation: str = "completion"  # e.g., "completion", "embedding", "batch"
    estimated_tokens: int | None = None
    retry_count: int = 0
    total_tokens_used: int = 0
    context_reductions: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "estimated_tokens": self.estimated_tokens,
            "retry_count": self.retry_count,
            "total_tokens_used": self.total_tokens_used,
            "context_reductions": self.context_reductions,
            **self.extra,
        }


class AICircuitBreaker:
    """
    Circuit breaker specialized for AI API interactions.

    Handles rate limit patterns separately from other failures, allowing
    intelligent recovery strategies for different failure modes.
    """

    def __init__(self, config: AICircuitBreakerConfig | None = None) -> None:
        """Initialize the AI circuit breaker."""
        self.config = config or AICircuitBreakerConfig()
        self._states: dict[str, AICircuitBreakerState] = {}
        self._lock = threading.RLock()

    def _get_state(self, key: str) -> AICircuitBreakerState:
        """Get or create circuit breaker state for a key."""
        with self._lock:
            if key not in self._states:
                self._states[key] = AICircuitBreakerState()
            return self._states[key]

    def check(self, key: str, failure_type: AIFailureType | None = None) -> bool:
        """
        Check if operation should be allowed.

        Args:
            key: Circuit identifier (e.g., "openai:gpt-4")
            failure_type: Optional failure type for specialized handling

        Returns:
            True if operation is allowed
        """
        with self._lock:
            state = self._get_state(key)

            if state.state == "closed":
                return True

            if state.state == "open":
                elapsed = time.time() - (state.last_failure_time or 0)

                # Use longer timeout for rate limits
                if state.consecutive_rate_limits >= self.config.consecutive_rate_limit_threshold:
                    timeout = self.config.rate_limit_open_duration
                else:
                    timeout = self.config.timeout_seconds

                if elapsed >= timeout:
                    logger.info(f"Circuit breaker transitioning to half_open for {key}")
                    state.state = "half_open"
                    state.half_open_calls = 0
                    return True
                return False

            if state.state == "half_open":
                if state.half_open_calls < self.config.half_open_max_calls:
                    state.half_open_calls += 1
                    return True
                return False

            return True

    def record_success(self, key: str) -> None:
        """Record successful operation."""
        with self._lock:
            state = self._get_state(key)

            if state.state == "half_open":
                state.success_count += 1
                if state.success_count >= self.config.success_threshold:
                    logger.info(f"Circuit breaker closed for {key} after recovery")
                    state.state = "closed"
                    state.failure_count = 0
                    state.success_count = 0
                    state.consecutive_rate_limits = 0
            elif state.state == "closed":
                state.failure_count = max(0, state.failure_count - 1)
                state.consecutive_rate_limits = max(0, state.consecutive_rate_limits - 1)

    def record_failure(self, key: str, failure_type: AIFailureType) -> None:
        """Record failed operation."""
        with self._lock:
            state = self._get_state(key)
            state.failure_count += 1
            state.last_failure_time = time.time()

            # Track consecutive rate limits separately
            if "rate_limit" in failure_type.value:
                state.consecutive_rate_limits += 1
                state.last_rate_limit_time = time.time()
            else:
                state.consecutive_rate_limits = max(0, state.consecutive_rate_limits - 1)

            if state.state == "half_open":
                logger.warning(f"Circuit breaker returning to open for {key}")
                state.state = "open"
                state.success_count = 0
            elif state.state == "closed":
                threshold = self.config.failure_threshold
                # Lower threshold for repeated rate limits
                if state.consecutive_rate_limits >= self.config.consecutive_rate_limit_threshold:
                    threshold = max(2, threshold - 2)

                if state.failure_count >= threshold:
                    logger.warning(f"Circuit breaker opened for {key} after {state.failure_count} failures")
                    state.state = "open"

    def reset(self, key: str) -> None:
        """Manually reset circuit breaker for a key."""
        with self._lock:
            if key in self._states:
                self._states[key] = AICircuitBreakerState()
                logger.info(f"Circuit breaker reset for {key}")

    def get_status(self, key: str) -> dict[str, Any]:
        """Get circuit breaker status for a key."""
        with self._lock:
            state = self._get_state(key)
            return {
                "key": key,
                "state": state.state,
                "failure_count": state.failure_count,
                "success_count": state.success_count,
                "consecutive_rate_limits": state.consecutive_rate_limits,
                "last_failure_time": state.last_failure_time,
                "last_rate_limit_time": state.last_rate_limit_time,
            }


class AIAdaptiveRetryStrategy(AdaptiveRetryStrategy):
    """
    Extended adaptive retry strategy with AI-specific optimizations.

    Provides intelligent retry logic for AI API calls with:
    - Specialized handling for rate limits (token vs request based)
    - Context length error recovery with auto-reduction
    - Model overload detection and backoff
    - Anti-bot detection handling
    - Provider-specific retry patterns
    """

    def __init__(
        self,
        history_file: str | None = None,
        max_history_size: int = 10000,
        ai_config: AIRetryConfig | None = None,
    ) -> None:
        """Initialize AI-specific retry strategy."""
        super().__init__(history_file, max_history_size)
        self.ai_config = ai_config or AIRetryConfig()

        # AI-specific default configs that override base configs
        self._init_ai_configs()

    def _init_ai_configs(self) -> None:
        """Initialize AI-specific retry configurations."""
        ai_rate_limit_config = AdaptiveRetryConfig(
            max_retries=5,
            base_delay=1.0,
            max_delay=60.0,
            backoff_multiplier=2.0,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        )

        ai_overload_config = AdaptiveRetryConfig(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            backoff_multiplier=1.5,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        )

        ai_timeout_config = AdaptiveRetryConfig(
            max_retries=3,
            base_delay=5.0,
            max_delay=60.0,
            backoff_multiplier=2.0,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        )

        ai_anti_bot_config = AdaptiveRetryConfig(
            max_retries=2,
            base_delay=30.0,
            max_delay=300.0,
            backoff_multiplier=2.0,
            strategy=RetryStrategy.EXTENDED_WAIT,
        )

        # Map AI failure types to configs (stored separately from base failure types)
        self.ai_configs: dict[AIFailureType, AdaptiveRetryConfig] = {
            AIFailureType.RATE_LIMIT_TIER1: ai_rate_limit_config,
            AIFailureType.RATE_LIMIT_TIER2: ai_rate_limit_config,
            AIFailureType.RATE_LIMIT_TIER3: AdaptiveRetryConfig(
                max_retries=0,  # Hard limit - don't retry
                base_delay=0.0,
                max_delay=0.0,
                backoff_multiplier=1.0,
                strategy=RetryStrategy.IMMEDIATE_RETRY,
            ),
            AIFailureType.MODEL_OVERLOADED: ai_overload_config,
            AIFailureType.MODEL_UNAVAILABLE: ai_overload_config,
            AIFailureType.API_TIMEOUT: ai_timeout_config,
            AIFailureType.ANTI_BOT_DETECTED: ai_anti_bot_config,
            AIFailureType.IP_BLOCKED: ai_anti_bot_config,
        }

    def classify_ai_exception(
        self,
        exc: Exception,
        context: AIRetryContext | None = None,
    ) -> AIFailureType:
        """
        Classify an AI API exception into a specific AI failure type.

        Args:
            exc: The exception from the AI API
            context: Optional retry context

        Returns:
            Classified AI failure type
        """
        exc_str = str(exc).lower()
        exc_type = type(exc).__name__

        # Rate limit detection
        if any(term in exc_str for term in ["rate_limit", "rate limit", "too many requests", "ratelimit"]):
            # Determine rate limit tier
            if "token" in exc_str or "tpm" in exc_str or "tokens per minute" in exc_str:
                return AIFailureType.RATE_LIMIT_TIER2
            if "hard" in exc_str or "quota" in exc_str or "billing" in exc_str:
                return AIFailureType.RATE_LIMIT_TIER3
            return AIFailureType.RATE_LIMIT_TIER1

        # Context/token limit errors
        if any(
            term in exc_str
            for term in [
                "context_length_exceeded",
                "maximum context length",
                "token limit",
                "too many tokens",
            ]
        ):
            return AIFailureType.CONTEXT_LENGTH_EXCEEDED

        if "max_tokens" in exc_str or "maximum tokens" in exc_str:
            return AIFailureType.MAX_TOKENS_TOO_LOW

        # Model availability
        if any(term in exc_str for term in ["overloaded", "capacity", "too busy"]):
            return AIFailureType.MODEL_OVERLOADED

        if any(term in exc_str for term in ["unavailable", "model_not_found", "deprecated"]):
            return AIFailureType.MODEL_UNAVAILABLE

        # Content filtering
        if any(term in exc_str for term in ["content_filter", "content filter", "safety", "moderation"]):
            return AIFailureType.CONTENT_FILTERED

        # Timeout errors
        if any(term in exc_str for term in ["timeout", "timed out", "deadline exceeded"]):
            return AIFailureType.API_TIMEOUT

        # Authentication
        if any(term in exc_str for term in ["authentication", "unauthorized", "api key", "invalid key"]):
            return AIFailureType.AUTHENTICATION_ERROR

        # Anti-bot detection
        if any(term in exc_str for term in ["bot", "automated", "suspicious", "blocked", "denied"]):
            return AIFailureType.ANTI_BOT_DETECTED

        if "ip" in exc_str and any(term in exc_str for term in ["blocked", "banned", "blacklist"]):
            return AIFailureType.IP_BLOCKED

        # Default to generic API error
        return AIFailureType.API_ERROR

    def calculate_ai_delay(
        self,
        failure_type: AIFailureType,
        retry_count: int,
        context: AIRetryContext | None = None,
    ) -> float:
        """
        Calculate delay for AI-specific retry.

        Args:
            failure_type: The AI failure type
            retry_count: Current retry attempt (0-based)
            context: Optional retry context

        Returns:
            Delay in seconds
        """
        config = self.ai_configs.get(failure_type)
        if not config:
            # Fallback to base calculation
            base_config = self.default_configs.get(FailureType.NETWORK_ERROR, self._get_fallback_config())
            return self.calculate_delay(base_config, retry_count)

        # Get base delay from config
        delay = config.base_delay * (config.backoff_multiplier**retry_count)
        delay = min(delay, config.max_delay)

        # Add provider-specific adjustments
        if context:
            if context.provider == "openai":
                # OpenAI often needs longer delays for rate limits
                if "rate_limit" in failure_type.value:
                    delay *= 1.5
            elif context.provider == "anthropic":
                # Anthropic has more aggressive rate limits
                if "rate_limit" in failure_type.value:
                    delay *= 2.0

        # Add jitter to prevent thundering herd
        if self.ai_config.enable_jitter:
            jitter = delay * self.ai_config.jitter_factor * random.random()
            delay += jitter

        return delay

    def should_reduce_context(self, failure_type: AIFailureType, context: AIRetryContext) -> bool:
        """Determine if context should be reduced for context length errors."""
        if not self.ai_config.auto_reduce_context:
            return False

        if failure_type != AIFailureType.CONTEXT_LENGTH_EXCEEDED:
            return False

        if context.context_reductions >= 3:  # Max 3 reductions
            return False

        return True

    def calculate_context_reduction(
        self,
        current_tokens: int | None,
        context: AIRetryContext,
    ) -> int | None:
        """Calculate new target token count after reduction."""
        if current_tokens is None:
            return None

        new_tokens = int(current_tokens * self.ai_config.context_reduction_factor)
        return max(new_tokens, self.ai_config.min_context_tokens)


class AIRetryResult:
    """Result of an AI retry operation."""

    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: Exception | None = None,
        attempts: int = 0,
        total_delay: float = 0.0,
        failure_type: AIFailureType | None = None,
        context_reduced: bool = False,
        cancelled: bool = False,
    ):
        self.success = success
        self.result = result
        self.error = error
        self.attempts = attempts
        self.total_delay = total_delay
        self.failure_type = failure_type
        self.context_reduced = context_reduced
        self.cancelled = cancelled

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "success": self.success,
            "attempts": self.attempts,
            "total_delay": self.total_delay,
            "failure_type": self.failure_type.value if self.failure_type else None,
            "context_reduced": self.context_reduced,
            "cancelled": self.cancelled,
            "error": str(self.error) if self.error else None,
        }


class AIRetryExecutor:
    """
    Executor for AI operations with intelligent retry logic.

    Combines adaptive retry strategy with circuit breaker protection
    specifically designed for AI API interactions.
    """

    def __init__(
        self,
        strategy: AIAdaptiveRetryStrategy | None = None,
        circuit_breaker: AICircuitBreaker | None = None,
        config: AIRetryConfig | None = None,
    ) -> None:
        """Initialize the AI retry executor."""
        self.strategy = strategy or AIAdaptiveRetryStrategy()
        self.circuit_breaker = circuit_breaker or AICircuitBreaker()
        self.config = config or AIRetryConfig()

        # Context reduction callbacks
        self._context_reducers: list[Callable[[int], int]] = []

    def register_context_reducer(self, reducer: Callable[[int], int]) -> None:
        """Register a callback for context reduction."""
        self._context_reducers.append(reducer)

    async def execute(
        self,
        operation: Callable[[], T],
        context: AIRetryContext,
        stop_event: threading.Event | None = None,
        on_retry: Callable[[int, Exception, float], None] | None = None,
    ) -> AIRetryResult:
        """
        Execute an AI operation with retry logic.

        Args:
            operation: Async or sync callable to execute
            context: AI retry context with provider/model info
            stop_event: Optional event for cancellation
            on_retry: Optional callback(attempt, error, delay)

        Returns:
            AIRetryResult with success status and details
        """
        circuit_key = f"{context.provider}:{context.model or 'default'}"

        # Check circuit breaker
        if not self.circuit_breaker.check(circuit_key):
            return AIRetryResult(
                success=False,
                error=CircuitBreakerOpenError(f"Circuit breaker open for {circuit_key}"),
                attempts=0,
            )

        attempt = 0
        total_delay = 0.0
        last_error: Exception | None = None
        last_failure_type: AIFailureType | None = None
        context_reduced = False

        # Determine max retries based on provider
        max_retries = self._get_max_retries(context)

        while attempt <= max_retries:
            context.retry_count = attempt

            start_time = time.time()
            try:
                # Execute operation
                result = operation()
                if asyncio.iscoroutine(result):
                    result = await result

                duration = time.time() - start_time

                # Success!
                self.circuit_breaker.record_success(circuit_key)
                self.strategy.record_failure(
                    FailureContext(
                        site_name=context.provider,
                        action=context.operation,
                        retry_count=attempt,
                        context=context.to_dict(),
                        failure_type=FailureType.NETWORK_ERROR,  # Placeholder for success
                    ),
                    success_after_retry=attempt > 0,
                    final_success=True,
                )

                return AIRetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                    context_reduced=context_reduced,
                )

            except Exception as exc:
                duration = time.time() - start_time
                last_error = exc

                # Classify the error
                last_failure_type = self.strategy.classify_ai_exception(exc, context)
                logger.warning(f"AI operation failed (attempt {attempt + 1}/{max_retries + 1}): {last_failure_type.value} - {exc}")

                # Record failure
                self.circuit_breaker.record_failure(circuit_key, last_failure_type)

                # Check for non-retryable errors
                if not self._is_retryable(last_failure_type):
                    return AIRetryResult(
                        success=False,
                        error=exc,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        failure_type=last_failure_type,
                        context_reduced=context_reduced,
                    )

                # Check max retries
                if attempt >= max_retries:
                    return AIRetryResult(
                        success=False,
                        error=MaxRetriesExceededError(f"Max retries ({max_retries}) exceeded: {exc}"),
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        failure_type=last_failure_type,
                        context_reduced=context_reduced,
                    )

                # Handle context length errors with reduction
                if self.strategy.should_reduce_context(last_failure_type, context):
                    new_tokens = self.strategy.calculate_context_reduction(context.estimated_tokens, context)
                    if new_tokens and context.estimated_tokens:
                        logger.info(f"Reducing context from {context.estimated_tokens} to {new_tokens} tokens")
                        context.estimated_tokens = new_tokens
                        context.context_reductions += 1
                        context_reduced = True

                        # Invoke context reducers
                        for reducer in self._context_reducers:
                            try:
                                reducer(new_tokens)
                            except Exception as e:
                                logger.warning(f"Context reducer failed: {e}")

                        # Don't increment attempt for context reduction
                        continue

                # Calculate delay
                delay = self.strategy.calculate_ai_delay(last_failure_type, attempt, context)
                total_delay += delay

                # Notify callback
                if on_retry:
                    try:
                        on_retry(attempt, exc, delay)
                    except Exception as cb_err:
                        logger.debug(f"Retry callback error: {cb_err}")

                # Check cancellation
                if stop_event and stop_event.is_set():
                    return AIRetryResult(
                        success=False,
                        error=last_error,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        failure_type=last_failure_type,
                        context_reduced=context_reduced,
                        cancelled=True,
                    )

                logger.info(f"Waiting {delay:.2f}s before retry {attempt + 2}")
                await asyncio.sleep(delay)

                attempt += 1

        # Should not reach here
        return AIRetryResult(
            success=False,
            error=last_error,
            attempts=attempt,
            total_delay=total_delay,
            failure_type=last_failure_type,
            context_reduced=context_reduced,
        )

    def _get_max_retries(self, context: AIRetryContext) -> int:
        """Determine max retries based on context."""
        # Provider-specific defaults
        defaults = {
            "openai": 5,
            "anthropic": 3,
            "google": 3,
            "azure": 5,
        }
        return defaults.get(context.provider, 3)

    def _is_retryable(self, failure_type: AIFailureType) -> bool:
        """Check if a failure type is retryable."""
        non_retryable = {
            AIFailureType.AUTHENTICATION_ERROR,
            AIFailureType.INVALID_REQUEST,
            AIFailureType.CONTENT_FILTERED,
            AIFailureType.SAFETY_VIOLATION,
            AIFailureType.MODEL_DEPRECATED,
            AIFailureType.RATE_LIMIT_TIER3,  # Hard limit
        }
        return failure_type not in non_retryable


def ai_retry(
    provider: str = "openai",
    model: str | None = None,
    operation: str = "completion",
    max_retries: int | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    stop_event: threading.Event | None = None,
    config: AIRetryConfig | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for AI operations with automatic retry logic.

    Args:
        provider: AI provider name ("openai", "anthropic", etc.)
        model: Model name (e.g., "gpt-4", "claude-3-opus")
        operation: Type of operation ("completion", "embedding", etc.)
        max_retries: Override default max retries
        on_retry: Optional callback(attempt, error, delay)
        stop_event: Optional event for cancellation
        config: Optional AIRetryConfig

    Example:
        @ai_retry(provider="openai", model="gpt-4")
        async def generate_text(prompt: str) -> str:
            return await openai.chat.completions.create(...)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build context
            ctx = AIRetryContext(
                provider=provider,
                model=model,
                operation=operation,
            )

            if max_retries is not None:
                # Temporarily override config
                pass  # Config is handled by executor

            executor = AIRetryExecutor(config=config)

            async def operation_fn() -> Any:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result

            retry_result = await executor.execute(
                operation=operation_fn,
                context=ctx,
                stop_event=stop_event,
                on_retry=on_retry,
            )

            if retry_result.success:
                return retry_result.result

            if retry_result.error:
                raise retry_result.error

            raise RuntimeError("AI retry failed without error")

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # For sync functions, run async wrapper in event loop
            return asyncio.run(async_wrapper(*args, **kwargs))

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Convenience aliases for common providers
def openai_retry(
    model: str | None = None,
    **kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator specifically for OpenAI API calls."""
    return ai_retry(provider="openai", model=model, **kwargs)


def anthropic_retry(
    model: str | None = None,
    **kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator specifically for Anthropic API calls."""
    return ai_retry(provider="anthropic", model=model, **kwargs)


def google_retry(
    model: str | None = None,
    **kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator specifically for Google AI API calls."""
    return ai_retry(provider="google", model=model, **kwargs)


# Module exports
__all__ = [
    # Core classes
    "AIAdaptiveRetryStrategy",
    "AICircuitBreaker",
    "AICircuitBreakerConfig",
    "AICircuitBreakerState",
    "AIRetryConfig",
    "AIRetryContext",
    "AIRetryExecutor",
    "AIRetryResult",
    "AIFailureType",
    # Decorators
    "ai_retry",
    "openai_retry",
    "anthropic_retry",
    "google_retry",
]
