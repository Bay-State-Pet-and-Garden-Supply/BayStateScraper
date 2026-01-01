"""
Adaptive Retry Strategy for Intelligent Scraping Operations

Provides dynamic retry configuration based on failure history and patterns.
Learns from past failures to optimize scraping efficiency and success rates.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from scraper_backend.core.failure_classifier import FailureType

logger = logging.getLogger(__name__)


class RetryStrategy(Enum):
    """Different retry strategies for various failure types."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    IMMEDIATE_RETRY = "immediate_retry"
    EXTENDED_WAIT = "extended_wait"
    SESSION_ROTATION = "session_rotation"
    CAPTCHA_SOLVE = "captcha_solve"


# Constants for adaptive strategy
RECENT_OCCURRENCES_THRESHOLD = 10
MAX_RETRIES_CAP = 10
LOW_SUCCESS_RATE_THRESHOLD = 0.3
HIGH_SUCCESS_RATE_THRESHOLD = 0.8
CONSECUTIVE_FAILURES_THRESHOLD = 2
PEAK_HOUR_WINDOW = 2
LOW_SUCCESS_RATE_INSIGHT_THRESHOLD = 0.5
CONSECUTIVE_FAILURES_INSIGHT_THRESHOLD = 3
HIGH_RETRY_COUNT_INSIGHT_THRESHOLD = 2.0

# Multipliers
DELAY_INCREASE_MULTIPLIER = 1.5
MAX_DELAY_INCREASE_MULTIPLIER = 2.0
BACKOFF_INCREASE_MULTIPLIER = 1.2
DELAY_DECREASE_MULTIPLIER = 0.8
MAX_DELAY_DECREASE_MULTIPLIER = 0.9
TIMEOUT_MULTIPLIER_INCREMENT = 0.2
TIMEOUT_MULTIPLIER_CAP = 3.0
PEAK_HOUR_DELAY_MULTIPLIER = 1.3


@dataclass
class FailureContext:
    """Context information for a failure."""

    site_name: str
    action: str
    retry_count: int
    context: dict[str, Any]
    failure_type: FailureType


@dataclass
class FailureRecord:
    """Record of a single failure occurrence."""

    timestamp: float
    failure_context: FailureContext
    success_after_retry: bool = False
    final_success: bool = False

    @property
    def failure_type(self) -> FailureType:
        return self.failure_context.failure_type

    @property
    def site_name(self) -> str:
        return self.failure_context.site_name

    @property
    def action(self) -> str:
        return self.failure_context.action

    @property
    def retry_count(self) -> int:
        return self.failure_context.retry_count


@dataclass
class FailurePattern:
    """Aggregated failure pattern for analysis."""

    failure_type: FailureType
    site_name: str
    total_occurrences: int
    recent_occurrences: int  # Last 24 hours
    success_rate: float  # Success rate after retries
    average_retry_count: float
    last_occurrence: float
    peak_failure_hour: int | None = None
    consecutive_failures: int = 0


@dataclass
class AdaptiveRetryConfig:
    """Adaptive retry configuration for a specific failure scenario."""

    max_retries: int
    base_delay: float
    max_delay: float
    backoff_multiplier: float
    strategy: RetryStrategy
    timeout_multiplier: float = 1.0
    session_rotation_threshold: int = 5
    captcha_retry_limit: int = 3


class AdaptiveRetryStrategy:
    """
    Adaptive retry strategy that learns from failure patterns to optimize scraping operations.

    Tracks failure history per site and failure type, analyzes patterns, and generates
    intelligent retry configurations that adapt to site behavior.
    """

    def __init__(self, history_file: str | None = None, max_history_size: int = 10000):
        """
        Initialize the adaptive retry strategy.

        Args:
            history_file: Path to persist failure history across sessions
            max_history_size: Maximum number of failure records to keep in memory
        """
        self.history_file = Path(history_file) if history_file else None
        self.max_history_size = max_history_size

        # In-memory failure history
        self.failure_history: list[FailureRecord] = []
        self.failure_patterns: dict[tuple[str, FailureType], FailurePattern] = {}

        # Load persisted history if available
        self._load_history()

        # Default retry configurations for different failure types
        # NOTE: Retry counts increased from 1 to 2-3 for better reliability (2024-12 update)
        self.default_configs = {
            FailureType.CAPTCHA_DETECTED: AdaptiveRetryConfig(
                max_retries=2,
                base_delay=5.0,
                max_delay=60.0,
                backoff_multiplier=2.0,
                strategy=RetryStrategy.CAPTCHA_SOLVE,
                captcha_retry_limit=2,
            ),
            FailureType.RATE_LIMITED: AdaptiveRetryConfig(
                max_retries=3,
                base_delay=10.0,
                max_delay=300.0,
                backoff_multiplier=2.0,
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            ),
            FailureType.LOGIN_FAILED: AdaptiveRetryConfig(
                max_retries=2,
                base_delay=2.0,
                max_delay=30.0,
                backoff_multiplier=1.5,
                strategy=RetryStrategy.EXTENDED_WAIT,
                session_rotation_threshold=1,
            ),
            FailureType.ACCESS_DENIED: AdaptiveRetryConfig(
                max_retries=2,
                base_delay=15.0,
                max_delay=120.0,
                backoff_multiplier=2.0,
                strategy=RetryStrategy.SESSION_ROTATION,
                session_rotation_threshold=1,
            ),
            FailureType.NETWORK_ERROR: AdaptiveRetryConfig(
                max_retries=3,
                base_delay=1.0,
                max_delay=30.0,
                backoff_multiplier=1.5,
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            ),
            FailureType.ELEMENT_MISSING: AdaptiveRetryConfig(
                max_retries=2,
                base_delay=0.5,
                max_delay=5.0,
                backoff_multiplier=1.2,
                strategy=RetryStrategy.LINEAR_BACKOFF,
                timeout_multiplier=1.5,
            ),
            FailureType.PAGE_NOT_FOUND: AdaptiveRetryConfig(
                max_retries=1,
                base_delay=0.0,
                max_delay=0.0,
                backoff_multiplier=1.0,
                strategy=RetryStrategy.IMMEDIATE_RETRY,
            ),
            FailureType.NO_RESULTS: AdaptiveRetryConfig(
                max_retries=1,
                base_delay=0.0,
                max_delay=0.0,
                backoff_multiplier=1.0,
                strategy=RetryStrategy.IMMEDIATE_RETRY,
            ),
            FailureType.TIMEOUT: AdaptiveRetryConfig(
                max_retries=3,
                base_delay=2.0,
                max_delay=15.0,
                backoff_multiplier=1.5,
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
                timeout_multiplier=1.2,
            ),
        }

    def record_failure(
        self,
        failure_context: FailureContext,
        success_after_retry: bool = False,
        final_success: bool = False,
    ) -> None:
        """
        Record a failure occurrence for learning and analysis.

        Args:
            failure_context: Context information about the failure
            success_after_retry: Whether operation succeeded after retries
            final_success: Whether operation ultimately succeeded
        """
        record = FailureRecord(
            timestamp=time.time(),
            failure_context=failure_context,
            success_after_retry=success_after_retry,
            final_success=final_success,
        )

        # Add to history
        self.failure_history.append(record)

        # Maintain history size limit
        if len(self.failure_history) > self.max_history_size:
            self.failure_history.pop(0)

        # Update patterns
        self._update_patterns(record)

        # Persist history
        self._save_history()

        logger.debug(
            f"Recorded failure: {failure_context.failure_type.value} on "
            f"{failure_context.site_name} during {failure_context.action} "
            f"(retry_count: {failure_context.retry_count}, success: {final_success})"
        )

    def get_adaptive_config(
        self, failure_type: FailureType, site_name: str, current_retry_count: int = 0
    ) -> AdaptiveRetryConfig:
        """
        Generate adaptive retry configuration based on failure history.

        Args:
            failure_type: Type of failure being handled
            site_name: Site where failure occurred
            current_retry_count: Current number of retries attempted

        Returns:
            AdaptiveRetryConfig with optimized retry parameters
        """
        # Start with default configuration
        config = self.default_configs.get(failure_type, self._get_fallback_config())

        # Get failure pattern for this site/failure combination
        pattern_key = (site_name, failure_type)
        pattern = self.failure_patterns.get(pattern_key)

        if pattern:
            # Adapt configuration based on pattern analysis
            config = self._adapt_config_from_pattern(config, pattern, current_retry_count)

        return config

    def analyze_failure_patterns(self, site_name: str | None = None) -> dict[str, Any]:
        """
        Analyze failure patterns for insights and optimization.

        Args:
            site_name: Optional site name to filter analysis

        Returns:
            Dictionary with pattern analysis results
        """
        patterns_to_analyze = self.failure_patterns

        if site_name:
            patterns_to_analyze = {
                k: v for k, v in self.failure_patterns.items() if k[0] == site_name
            }

        analysis: dict[str, Any] = {
            "total_failures": len(self.failure_history),
            "patterns": {},
            "insights": [],
        }

        patterns_dict = analysis["patterns"]
        insights_list = analysis["insights"]

        for (site, failure_type), pattern in patterns_to_analyze.items():
            pattern_analysis = self._analyze_pattern(pattern)
            patterns_dict[f"{site}_{failure_type.value}"] = pattern_analysis

            # Generate insights
            insights = self._generate_insights(pattern, pattern_analysis)
            insights_list.extend(insights)

        return analysis

    def _update_patterns(self, record: FailureRecord) -> None:
        """Update failure patterns based on new failure record."""
        key = (record.site_name, record.failure_type)
        current_time = time.time()

        if key not in self.failure_patterns:
            self.failure_patterns[key] = FailurePattern(
                failure_type=record.failure_type,
                site_name=record.site_name,
                total_occurrences=0,
                recent_occurrences=0,
                success_rate=0.0,
                average_retry_count=0.0,
                last_occurrence=current_time,
            )

        pattern: FailurePattern = self.failure_patterns[key]

        # Update counters
        pattern.total_occurrences += 1
        pattern.last_occurrence = current_time

        # Count recent occurrences (last 24 hours)
        recent_threshold = current_time - (24 * 60 * 60)
        pattern.recent_occurrences = sum(
            1
            for r in self.failure_history
            if r.site_name == record.site_name
            and r.failure_type == record.failure_type
            and r.timestamp > recent_threshold
        )

        # Update success rate and retry statistics
        successful_retries = [
            r
            for r in self.failure_history
            if r.site_name == record.site_name
            and r.failure_type == record.failure_type
            and (r.success_after_retry or r.final_success)
        ]

        if pattern.total_occurrences > 0:
            pattern.success_rate = len(successful_retries) / pattern.total_occurrences

        # Update average retry count
        all_retries = [
            r.retry_count
            for r in self.failure_history
            if r.site_name == record.site_name and r.failure_type == record.failure_type
        ]
        if all_retries:
            pattern.average_retry_count = sum(all_retries) / len(all_retries)

        # Update consecutive failures
        if record.final_success:
            pattern.consecutive_failures = 0
        else:
            pattern.consecutive_failures += 1

        # Analyze peak failure hours
        failure_hours = [
            time.localtime(r.timestamp).tm_hour
            for r in self.failure_history
            if r.site_name == record.site_name and r.failure_type == record.failure_type
        ]
        if failure_hours:
            hour_counts: dict[int, int] = defaultdict(int)
            for hour in failure_hours:
                hour_counts[hour] += 1
            pattern.peak_failure_hour = max(hour_counts.keys(), key=lambda h: hour_counts[h])

    def _adapt_config_from_pattern(
        self, config: AdaptiveRetryConfig, pattern: FailurePattern, current_retry_count: int
    ) -> AdaptiveRetryConfig:
        """Adapt retry configuration based on failure pattern analysis."""
        adapted_config = AdaptiveRetryConfig(**asdict(config))

        # Increase max retries for frequently failing sites
        if pattern.recent_occurrences > RECENT_OCCURRENCES_THRESHOLD:
            adapted_config.max_retries = min(config.max_retries + 2, MAX_RETRIES_CAP)

        # Adjust delays based on success rate
        if pattern.success_rate < LOW_SUCCESS_RATE_THRESHOLD:  # Low success rate
            adapted_config.base_delay *= DELAY_INCREASE_MULTIPLIER
            adapted_config.max_delay *= MAX_DELAY_INCREASE_MULTIPLIER
            adapted_config.backoff_multiplier *= BACKOFF_INCREASE_MULTIPLIER
        elif pattern.success_rate > HIGH_SUCCESS_RATE_THRESHOLD:  # High success rate
            adapted_config.base_delay *= DELAY_DECREASE_MULTIPLIER
            adapted_config.max_delay *= MAX_DELAY_DECREASE_MULTIPLIER

        # Increase timeout multiplier for element missing failures
        if pattern.failure_type == FailureType.ELEMENT_MISSING:
            adapted_config.timeout_multiplier = min(
                config.timeout_multiplier + TIMEOUT_MULTIPLIER_INCREMENT, TIMEOUT_MULTIPLIER_CAP
            )

        # Lower session rotation threshold for access denied failures
        if (
            pattern.failure_type == FailureType.ACCESS_DENIED
            and pattern.consecutive_failures > CONSECUTIVE_FAILURES_THRESHOLD
        ):
            adapted_config.session_rotation_threshold = max(
                config.session_rotation_threshold - 1, 1
            )

        # Adjust for peak failure hours
        current_hour = time.localtime().tm_hour
        if (
            pattern.peak_failure_hour is not None
            and abs(current_hour - pattern.peak_failure_hour) <= PEAK_HOUR_WINDOW
        ):
            adapted_config.base_delay *= PEAK_HOUR_DELAY_MULTIPLIER  # Increase delay in peak hours

        return adapted_config

    def _analyze_pattern(self, pattern: FailurePattern) -> dict[str, Any]:
        """Analyze a single failure pattern for insights."""
        return {
            "total_occurrences": pattern.total_occurrences,
            "recent_occurrences": pattern.recent_occurrences,
            "success_rate": pattern.success_rate,
            "average_retry_count": pattern.average_retry_count,
            "consecutive_failures": pattern.consecutive_failures,
            "peak_failure_hour": pattern.peak_failure_hour,
            "last_occurrence_hours_ago": (time.time() - pattern.last_occurrence) / 3600,
            "failure_frequency_per_hour": pattern.recent_occurrences / 24,
        }

    def _generate_insights(self, pattern: FailurePattern, analysis: dict[str, Any]) -> list[str]:
        """Generate actionable insights from pattern analysis."""
        insights = []

        if analysis["failure_frequency_per_hour"] > 1.0:
            insights.append(
                f"High failure frequency for {pattern.failure_type.value} on {pattern.site_name}: "
                f"{analysis['failure_frequency_per_hour']:.1f} failures/hour"
            )

        if analysis["success_rate"] < LOW_SUCCESS_RATE_INSIGHT_THRESHOLD:
            insights.append(
                f"Low success rate for {pattern.failure_type.value} on {pattern.site_name}: "
                f"{analysis['success_rate']:.1%}"
            )

        if analysis["consecutive_failures"] > CONSECUTIVE_FAILURES_INSIGHT_THRESHOLD:
            insights.append(
                f"Consecutive failures for {pattern.failure_type.value} on {pattern.site_name}: "
                f"{analysis['consecutive_failures']} failures in a row"
            )

        if analysis["average_retry_count"] > HIGH_RETRY_COUNT_INSIGHT_THRESHOLD:
            insights.append(
                f"High retry count needed for {pattern.failure_type.value} on {pattern.site_name}: "
                f"{analysis['average_retry_count']:.1f} average retries"
            )

        return insights

    def _get_fallback_config(self) -> AdaptiveRetryConfig:
        """Get fallback retry configuration for unknown failure types."""
        return AdaptiveRetryConfig(
            max_retries=1,
            base_delay=1.0,
            max_delay=30.0,
            backoff_multiplier=2.0,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        )

    def _load_history(self) -> None:
        """Load failure history from persistent storage."""
        if not self.history_file or not self.history_file.exists():
            return

        try:
            with open(self.history_file) as f:
                data = json.load(f)

            # Reconstruct failure records
            for record_data in data.get("failure_history", []):
                # Convert string back to enum
                if "failure_type" in record_data:
                    # Handle legacy format where failure_type was direct
                    record_data["failure_context"] = {
                        "failure_type": FailureType(record_data.pop("failure_type")),
                        "site_name": record_data.pop("site_name"),
                        "action": record_data.pop("action"),
                        "retry_count": record_data.pop("retry_count"),
                        "context": record_data.pop("context"),
                    }

                # Handle new format
                if isinstance(record_data.get("failure_context"), dict):
                    ctx = record_data["failure_context"]
                    if isinstance(ctx.get("failure_type"), str):
                        ctx["failure_type"] = FailureType(ctx["failure_type"])
                    record_data["failure_context"] = FailureContext(**ctx)

                record = FailureRecord(**record_data)
                self.failure_history.append(record)
                self._update_patterns(record)

            logger.info(
                f"Loaded {len(self.failure_history)} failure records from {self.history_file}"
            )

        except Exception as e:
            logger.warning(f"Failed to load failure history: {e}")

    def _save_history(self) -> None:  # type: ignore
        """Save failure history to persistent storage."""
        if not self.history_file:
            return

        try:
            # Ensure directory exists
            self.history_file.parent.mkdir(parents=True, exist_ok=True)

            # Convert records to dictionaries with enum handling
            def serialize_record(record: FailureRecord) -> dict[str, Any]:
                context_dict = {
                    "site_name": record.site_name,
                    "action": record.action,
                    "retry_count": record.retry_count,
                    "context": record.failure_context.context,
                    "failure_type": record.failure_type.value,
                }
                data: dict[str, Any] = {
                    "timestamp": record.timestamp,
                    "failure_context": context_dict,
                    "success_after_retry": record.success_after_retry,
                    "final_success": record.final_success,
                }
                return data

            data: dict[str, Any] = {  # type: ignore
                "failure_history": [
                    serialize_record(record) for record in self.failure_history[-1000:]
                ],  # Keep last 1000
                "timestamp": time.time(),
            }

            with open(self.history_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.warning(f"Failed to save failure history: {e}")

    def calculate_delay(self, config: AdaptiveRetryConfig, retry_count: int) -> float:
        """
        Calculate delay for a specific retry attempt.

        Args:
            config: Retry configuration
            retry_count: Current retry count (0-based)

        Returns:
            Delay in seconds
        """
        delay = 0.0

        if config.strategy == RetryStrategy.IMMEDIATE_RETRY:
            delay = 0.0

        elif config.strategy == RetryStrategy.FIXED_DELAY:
            delay = config.base_delay

        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * (retry_count + 1)

        elif config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay * (config.backoff_multiplier**retry_count)
            delay = min(delay, config.max_delay)

        elif config.strategy == RetryStrategy.EXTENDED_WAIT:
            # Longer initial wait, then exponential
            if retry_count == 0:
                delay = config.base_delay * 3
            else:
                delay = config.base_delay * (config.backoff_multiplier**retry_count)
                delay = min(delay, config.max_delay)

        else:
            # Default to exponential backoff
            delay = config.base_delay * (config.backoff_multiplier**retry_count)
            delay = min(delay, config.max_delay)

        return delay
