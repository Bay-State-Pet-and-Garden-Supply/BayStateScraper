"""
Failure Analytics and Reporting System

Provides comprehensive failure tracking, analysis, and insights for scraper optimization.
Collects failure data across all scrapers and generates actionable reports.
"""
from __future__ import annotations


import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.failure_classifier import FailureType
from core.settings_manager import PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass
class FailureRecord:
    """Individual failure record with detailed context."""

    site_name: str
    failure_type: FailureType
    timestamp: float
    duration: float | None = None
    action: str | None = None
    retry_count: int = 0
    context: dict[str, Any] | None = None
    success_after_retry: bool = False
    final_success: bool = False
    session_id: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["failure_type"] = self.failure_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureRecord":
        """Create from dictionary."""
        data_copy = data.copy()
        data_copy["failure_type"] = FailureType(data_copy["failure_type"])
        return cls(**data_copy)


@dataclass
class SiteMetrics:
    """Aggregated metrics for a specific site."""

    total_requests: int = 0
    total_failures: int = 0
    success_rate: float = 1.0
    failure_rate: float = 0.0
    avg_duration: float = 0.0
    failure_types: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    recent_failures: int = 0
    last_failure_time: float | None = None
    health_score: float = 1.0  # 0.0 to 1.0, higher is better


class FailureAnalytics:
    """
    Comprehensive failure analytics system for scraper optimization.

    Tracks failure patterns, generates insights, and provides actionable recommendations
    for improving scraper reliability and efficiency.
    """

    def __init__(
        self,
        max_records: int = 10000,
        retention_days: int = 30,
        data_dir: str | None = None,
    ):
        """
        Initialize the failure analytics system.

        Args:
            max_records: Maximum number of failure records to keep in memory
            retention_days: How long to retain failure data
            data_dir: Directory to store analytics data (defaults to PROJECT_ROOT/data/analytics)
        """
        self.max_records = max_records
        self.retention_days = retention_days

        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(PROJECT_ROOT) / "data" / "analytics"

        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Thread-safe data structures
        self._lock = threading.RLock()
        self._records: deque[FailureRecord] = deque(maxlen=max_records)
        self._site_metrics: dict[str, SiteMetrics] = defaultdict(lambda: SiteMetrics())
        self._failure_patterns: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Analytics data files
        self.records_file = self.data_dir / "failure_records.json"
        self.metrics_file = self.data_dir / "site_metrics.json"

        # Load existing data
        self._load_data()

        # Start background cleanup thread
        self._cleanup_thread = threading.Thread(target=self._background_cleanup, daemon=True)
        self._cleanup_thread.start()

        logger.info(
            f"FailureAnalytics initialized with max_records={max_records}, retention={retention_days} days"
        )

    def record_failure(
        self,
        site_name: str,
        failure_type: FailureType,
        duration: float | None = None,
        action: str | None = None,
        retry_count: int = 0,
        context: dict[str, Any] | None = None,
        success_after_retry: bool = False,
        final_success: bool = False,
        session_id: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """
        Record a failure occurrence with detailed context.

        Args:
            site_name: Name of the site where failure occurred
            failure_type: Type of failure
            duration: Time taken for the operation (seconds)
            action: The action that failed (e.g., 'navigate', 'extract')
            retry_count: Number of retries attempted
            context: Additional context information
            success_after_retry: Whether operation succeeded after retry
            final_success: Whether operation ultimately succeeded
            session_id: Browser session identifier
            user_agent: User agent string used
            ip_address: IP address used
        """
        record = FailureRecord(
            site_name=site_name,
            failure_type=failure_type,
            timestamp=time.time(),
            duration=duration,
            action=action,
            retry_count=retry_count,
            context=context or {},
            success_after_retry=success_after_retry,
            final_success=final_success,
            session_id=session_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        with self._lock:
            # Add to records
            self._records.append(record)

            # Update site metrics
            self._update_site_metrics(site_name, record)

            # Update failure patterns
            self._update_failure_patterns(site_name, failure_type, action)

        # Lightweight logging - only log significant failures
        if retry_count >= 3 or failure_type in [
            FailureType.ACCESS_DENIED,
            FailureType.RATE_LIMITED,
        ]:
            logger.warning(
                f"Failure recorded: {site_name} - {failure_type.value} "
                f"(retries: {retry_count}, action: {action})"
            )

    def record_success(
        self,
        site_name: str,
        duration: float | None = None,
        action: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """
        Record a successful operation.

        Args:
            site_name: Name of the site
            duration: Time taken for the operation (seconds)
            action: The action that succeeded
            session_id: Browser session identifier
        """
        with self._lock:
            metrics = self._site_metrics[site_name]
            metrics.total_requests += 1
            if duration:
                # Update rolling average duration
                metrics.avg_duration = (
                    (metrics.avg_duration * (metrics.total_requests - 1)) + duration
                ) / metrics.total_requests

    def get_site_metrics(self, site_name: str) -> SiteMetrics:
        """
        Get current metrics for a specific site.

        Args:
            site_name: Name of the site

        Returns:
            SiteMetrics object with current statistics
        """
        with self._lock:
            return self._site_metrics[site_name]

    def get_all_site_metrics(self) -> dict[str, SiteMetrics]:
        """
        Get metrics for all sites.

        Returns:
            Dictionary mapping site names to their metrics
        """
        with self._lock:
            return dict(self._site_metrics)

    def get_failure_patterns(
        self, site_name: str | None = None, hours: int = 24
    ) -> dict[str, dict[str, int]]:
        """
        Get failure patterns for analysis.

        Args:
            site_name: Specific site to analyze (None for all sites)
            hours: Time window in hours to analyze

        Returns:
            Nested dictionary of failure patterns
        """
        time.time() - (hours * 3600)

        with self._lock:
            if site_name:
                patterns = self._failure_patterns.get(site_name, defaultdict(int))
                return {site_name: dict(patterns)}
            else:
                result = {}
                for site, patterns in self._failure_patterns.items():
                    result[site] = dict(patterns)
                return result

    def generate_report(self, site_name: str | None = None, hours: int = 24) -> dict[str, Any]:
        """
        Generate a comprehensive analytics report.

        Args:
            site_name: Specific site to report on (None for all sites)
            hours: Time window in hours for the report

        Returns:
            Dictionary containing the analytics report
        """
        cutoff_time = time.time() - (hours * 3600)

        with self._lock:
            # Filter recent records
            recent_records = [
                r
                for r in self._records
                if r.timestamp >= cutoff_time and (site_name is None or r.site_name == site_name)
            ]

            if not recent_records:
                return {
                    "period_hours": hours,
                    "total_failures": 0,
                    "insights": ["No failure data available for the specified period"],
                    "recommendations": [],
                }

            # Analyze failure patterns
            failure_counts: dict[str, int] = defaultdict(int)
            site_failures: dict[str, int] = defaultdict(int)
            action_failures: dict[str, int] = defaultdict(int)
            type_action_combinations: dict[str, int] = defaultdict(int)

            for record in recent_records:
                failure_counts[record.failure_type.value] += 1
                site_failures[record.site_name] += 1
                if record.action:
                    action_failures[record.action] += 1
                    type_action_combinations[f"{record.failure_type.value}_{record.action}"] += 1

            # Generate insights
            insights = self._generate_insights(
                recent_records, failure_counts, site_failures, action_failures
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(
                failure_counts, site_failures, action_failures, type_action_combinations
            )

            # Calculate summary statistics
            total_failures = len(recent_records)
            avg_retry_count = sum(r.retry_count for r in recent_records) / total_failures
            success_after_retry_rate = (
                sum(1 for r in recent_records if r.success_after_retry) / total_failures
            )

            return {
                "period_hours": hours,
                "total_failures": total_failures,
                "failure_counts": dict(failure_counts),
                "site_failures": dict(site_failures),
                "action_failures": dict(action_failures),
                "avg_retry_count": round(avg_retry_count, 2),
                "success_after_retry_rate": round(success_after_retry_rate, 3),
                "insights": insights,
                "recommendations": recommendations,
                "generated_at": datetime.now().isoformat(),
            }

    def get_health_score(self, site_name: str) -> float:
        """
        Calculate a health score for a site (0.0 to 1.0, higher is better).

        Args:
            site_name: Name of the site

        Returns:
            Health score between 0.0 and 1.0
        """
        with self._lock:
            metrics = self._site_metrics.get(site_name)
            if not metrics or metrics.total_requests == 0:
                return 1.0  # No data = assume healthy

            # Factors affecting health score
            success_rate = metrics.success_rate
            recent_failure_rate = min(metrics.recent_failures / max(metrics.total_requests, 1), 1.0)

            # Weight factors (success rate is most important)
            health_score = success_rate * 0.7 + (1.0 - recent_failure_rate) * 0.3

            return round(health_score, 3)

    def _update_site_metrics(self, site_name: str, record: FailureRecord) -> None:
        """Update site metrics with a new failure record."""
        metrics = self._site_metrics[site_name]

        metrics.total_requests += 1
        metrics.total_failures += 1
        metrics.failure_rate = metrics.total_failures / metrics.total_requests
        metrics.success_rate = 1.0 - metrics.failure_rate

        metrics.failure_types[record.failure_type.value] += 1
        metrics.last_failure_time = record.timestamp
        metrics.recent_failures += 1

        # Update duration if available
        if record.duration:
            metrics.avg_duration = (
                (metrics.avg_duration * (metrics.total_requests - 1)) + record.duration
            ) / metrics.total_requests

        # Update health score
        metrics.health_score = self.get_health_score(site_name)

    def _update_failure_patterns(
        self, site_name: str, failure_type: FailureType, action: str | None
    ) -> None:
        """Update failure pattern tracking."""
        key = f"{failure_type.value}_{action or 'unknown'}"
        self._failure_patterns[site_name][key] += 1

    def _generate_insights(
        self,
        records: list[FailureRecord],
        failure_counts: dict[str, int],
        site_failures: dict[str, int],
        action_failures: dict[str, int],
    ) -> list[str]:
        """Generate insights from failure data."""
        insights = []

        # Most common failure types
        if failure_counts:
            most_common_failure = max(failure_counts.items(), key=lambda x: x[1])
            insights.append(
                f"Most common failure type: {most_common_failure[0]} "
                f"({most_common_failure[1]} occurrences)"
            )

        # Problematic sites
        if site_failures:
            worst_site = max(site_failures.items(), key=lambda x: x[1])
            insights.append(f"Most problematic site: {worst_site[0]} ({worst_site[1]} failures)")

        # Problematic actions
        if action_failures:
            worst_action = max(action_failures.items(), key=lambda x: x[1])
            insights.append(
                f"Most problematic action: {worst_action[0]} ({worst_action[1]} failures)"
            )

        # Retry success rate
        total_failures = len(records)
        if total_failures > 0:
            retry_successes = sum(1 for r in records if r.success_after_retry)
            if retry_successes > 0:
                retry_rate = retry_successes / total_failures
                insights.append(
                    f"Retry success rate: {retry_rate:.1%} "
                    f"({retry_successes}/{total_failures} failures recovered via retry)"
                )

        # Time-based patterns
        hour_counts: dict[int, int] = defaultdict(int)
        for record in records:
            hour = datetime.fromtimestamp(record.timestamp).hour
            hour_counts[hour] += 1

        if hour_counts:
            peak_hour = max(hour_counts.items(), key=lambda x: x[1])
            insights.append(f"Peak failure hour: {peak_hour[0]:02d}:00 ({peak_hour[1]} failures)")

        return insights

    def _generate_recommendations(
        self,
        failure_counts: dict[str, int],
        site_failures: dict[str, int],
        action_failures: dict[str, int],
        type_action_combinations: dict[str, int],
    ) -> list[str]:
        """Generate actionable recommendations based on failure patterns."""
        recommendations = []

        # Rate limiting recommendations
        HIGH_RATE_LIMIT_THRESHOLD = 0.3
        if failure_counts.get("rate_limited", 0) > 0:
            rate_limited_pct = failure_counts["rate_limited"] / sum(failure_counts.values())
            if rate_limited_pct > HIGH_RATE_LIMIT_THRESHOLD:
                recommendations.append(
                    "High rate limiting detected. Consider increasing delays between requests "
                    "and implementing more sophisticated rate limiting strategies."
                )

        # CAPTCHA recommendations
        HIGH_CAPTCHA_THRESHOLD = 0.2
        if failure_counts.get("captcha_detected", 0) > 0:
            captcha_pct = failure_counts["captcha_detected"] / sum(failure_counts.values())
            if captcha_pct > HIGH_CAPTCHA_THRESHOLD:
                recommendations.append(
                    "Frequent CAPTCHA detection. Consider implementing automated CAPTCHA solving "
                    "or adjusting scraping patterns to avoid detection."
                )

        # Access denied recommendations
        if failure_counts.get("access_denied", 0) > 0:
            recommendations.append(
                "Access denied errors detected. Consider rotating user agents, IP addresses, "
                "and implementing session management strategies."
            )

        HIGH_FAILURE_THRESHOLD = 10
        # Site-specific recommendations
        for site, failures in site_failures.items():
            if failures > HIGH_FAILURE_THRESHOLD:  # Arbitrary threshold
                recommendations.append(
                    f"High failure rate for {site}. Consider reviewing site-specific configuration "
                    "and implementing targeted anti-detection measures."
                )

        # Action-specific recommendations
        HIGH_LOGIN_FAILURE_THRESHOLD = 5
        if action_failures.get("login", 0) > HIGH_LOGIN_FAILURE_THRESHOLD:
            recommendations.append(
                "Login failures detected. Verify credentials and consider implementing "
                "credential rotation or alternative authentication methods."
            )

        if (
            action_failures.get("extract_single", 0)
            > action_failures.get("extract_multiple", 0) * 2
        ):
            recommendations.append(
                "High single element extraction failures. Consider reviewing selectors "
                "and implementing more robust element waiting strategies."
            )

        # General recommendations
        if not recommendations:
            recommendations.append(
                "Overall failure rates are within acceptable ranges. Continue monitoring."
            )

        return recommendations

    def _background_cleanup(self) -> None:
        """Background thread for periodic cleanup of old data."""
        while True:
            try:
                time.sleep(3600)  # Run cleanup every hour
                self._cleanup_old_data()
                self._save_data()
            except Exception as e:
                logger.error(f"Background cleanup failed: {e}")

    def _cleanup_old_data(self) -> None:
        """Remove data older than retention period."""
        cutoff_time = time.time() - (self.retention_days * 24 * 3600)

        with self._lock:
            # Remove old records
            while self._records and self._records[0].timestamp < cutoff_time:
                self._records.popleft()

            # Reset recent failure counters periodically
            for metrics in self._site_metrics.values():
                # Reset recent failures counter every few hours
                TWO_HOURS_IN_SECONDS = 7200
                if (
                    metrics.last_failure_time
                    and time.time() - metrics.last_failure_time > TWO_HOURS_IN_SECONDS
                ):  # 2 hours
                    metrics.recent_failures = max(0, metrics.recent_failures - 1)

    def _load_data(self) -> None:
        """Load persisted analytics data."""
        try:
            if self.records_file.exists():
                with open(self.records_file) as f:
                    records_data = json.load(f)
                    for record_data in records_data[-self.max_records :]:  # Load last N records
                        record = FailureRecord.from_dict(record_data)
                        self._records.append(record)
                        self._update_site_metrics(record.site_name, record)
                        self._update_failure_patterns(
                            record.site_name, record.failure_type, record.action
                        )
                logger.info(f"Loaded {len(self._records)} failure records from disk")

            if self.metrics_file.exists():
                with open(self.metrics_file) as f:
                    metrics_data = json.load(f)
                    for site, data in metrics_data.items():
                        # Convert failure_types back to defaultdict
                        data["failure_types"] = defaultdict(int, data.get("failure_types", {}))
                        self._site_metrics[site] = SiteMetrics(**data)
                logger.info(f"Loaded metrics for {len(self._site_metrics)} sites from disk")

        except Exception as e:
            logger.warning(f"Failed to load analytics data: {e}")

    def _save_data(self) -> None:
        """Persist analytics data to disk."""
        try:
            # Save records
            records_data = [record.to_dict() for record in self._records]
            with open(self.records_file, "w") as f:
                json.dump(records_data, f, indent=2)

            # Save metrics
            metrics_data = {}
            for site, metrics in self._site_metrics.items():
                data = asdict(metrics)
                # Convert defaultdict to regular dict for JSON serialization
                data["failure_types"] = dict(metrics.failure_types)
                metrics_data[site] = data

            with open(self.metrics_file, "w") as f:
                json.dump(metrics_data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save analytics data: {e}")

    def shutdown(self) -> None:
        """Shutdown the analytics system and save final data."""
        logger.info("Shutting down FailureAnalytics")
        self._save_data()


# Global instance
_analytics_instance = None


def get_failure_analytics() -> FailureAnalytics:
    """Get the global FailureAnalytics instance."""
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = FailureAnalytics()
    return _analytics_instance
