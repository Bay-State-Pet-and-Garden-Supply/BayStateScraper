"""
Scraper Health Monitoring and Diagnostics System

Provides comprehensive health monitoring for all scrapers including:
- Real-time health status tracking
- Performance metrics and trends
- Diagnostic information for troubleshooting
- Alerts and notifications for degraded scrapers
- Integration with FailureAnalytics for historical data
"""
from __future__ import annotations


import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from core.failure_analytics import FailureAnalytics, SiteMetrics
from core.failure_classifier import FailureType
from core.settings_manager import PROJECT_ROOT

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels for scrapers."""

    HEALTHY = "healthy"  # All systems operational, good success rate
    DEGRADED = "degraded"  # Some issues, reduced performance
    UNHEALTHY = "unhealthy"  # Significant issues, high failure rate
    CRITICAL = "critical"  # Scraper is effectively non-functional
    UNKNOWN = "unknown"  # No data available


@dataclass
class ScraperDiagnostics:
    """Detailed diagnostic information for a scraper."""

    scraper_name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    health_score: float = 1.0  # 0.0 to 1.0
    last_run_time: float | None = None
    last_success_time: float | None = None
    last_failure_time: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None

    # Performance metrics
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    success_rate: float = 1.0
    avg_duration_seconds: float = 0.0
    min_duration_seconds: float = 0.0
    max_duration_seconds: float = 0.0

    # Recent activity (last 24 hours)
    recent_runs: int = 0
    recent_successes: int = 0
    recent_failures: int = 0
    recent_success_rate: float = 1.0

    # Failure breakdown
    failure_types: dict[str, int] = field(default_factory=dict)
    most_common_failure: str | None = None

    # Circuit breaker status
    circuit_breaker_open: bool = False
    circuit_breaker_failures: int = 0

    # Configuration status
    config_valid: bool = True
    config_path: str | None = None
    has_test_skus: bool = False

    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScraperDiagnostics":
        """Create from dictionary."""
        data_copy = data.copy()
        data_copy["status"] = HealthStatus(data_copy.get("status", "unknown"))
        return cls(**data_copy)


@dataclass
class HealthAlert:
    """Health alert for a scraper."""

    scraper_name: str
    alert_type: str  # 'degraded', 'unhealthy', 'critical', 'recovered'
    message: str
    severity: str  # 'info', 'warning', 'error', 'critical'
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ScraperHealthMonitor:
    """
    Comprehensive health monitoring system for scrapers.

    Tracks health status, performance metrics, and provides diagnostics
    for all registered scrapers. Integrates with FailureAnalytics for
    historical data and trend analysis.
    """

    # Health score thresholds
    HEALTHY_THRESHOLD = 0.85
    DEGRADED_THRESHOLD = 0.60
    UNHEALTHY_THRESHOLD = 0.30

    def __init__(
        self,
        failure_analytics: FailureAnalytics | None = None,
        config_dir: str | Path | None = None,
        alert_callback: Callable[[HealthAlert], None] | None = None,
    ):
        """
        Initialize the health monitor.

        Args:
            failure_analytics: Optional FailureAnalytics instance for integration
            config_dir: Directory containing scraper configs (for validation)
            alert_callback: Optional callback for health alerts
        """
        self._lock = threading.RLock()

        # Core data structures
        self._diagnostics: dict[str, ScraperDiagnostics] = {}
        self._run_history: dict[str, list[dict[str, Any]]] = {}
        self._alerts: list[HealthAlert] = []
        self._alert_callback = alert_callback

        # Integration with failure analytics
        self._failure_analytics = failure_analytics

        # Config directory for validation
        if config_dir:
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = Path(PROJECT_ROOT) / "src" / "scrapers" / "configs"

        # Track previous health status for change detection
        self._previous_status: dict[str, HealthStatus] = {}

        # Background monitoring thread
        self._monitoring_active = True
        self._monitor_thread = threading.Thread(target=self._background_monitor, daemon=True)
        self._monitor_thread.start()

        logger.info("ScraperHealthMonitor initialized")

    def register_scraper(self, scraper_name: str) -> ScraperDiagnostics:
        """
        Register a scraper for health monitoring.

        Args:
            scraper_name: Name of the scraper to register

        Returns:
            ScraperDiagnostics instance for the scraper
        """
        with self._lock:
            if scraper_name not in self._diagnostics:
                diagnostics = ScraperDiagnostics(scraper_name=scraper_name)

                # Check config validity
                config_path = self._config_dir / f"{scraper_name}.yaml"
                diagnostics.config_path = str(config_path)
                diagnostics.config_valid = config_path.exists()

                if diagnostics.config_valid:
                    # Check for test SKUs
                    try:
                        import yaml

                        with open(config_path, encoding="utf-8") as f:
                            config = yaml.safe_load(f)
                            diagnostics.has_test_skus = bool(config.get("test_skus"))
                    except Exception:
                        pass

                self._diagnostics[scraper_name] = diagnostics
                self._run_history[scraper_name] = []
                logger.debug(f"Registered scraper: {scraper_name}")

            return self._diagnostics[scraper_name]

    def record_run_start(self, scraper_name: str) -> None:
        """
        Record the start of a scraper run.

        Args:
            scraper_name: Name of the scraper
        """
        with self._lock:
            if scraper_name not in self._diagnostics:
                self.register_scraper(scraper_name)

            diagnostics = self._diagnostics[scraper_name]
            diagnostics.last_run_time = time.time()
            diagnostics.updated_at = time.time()

    def record_run_success(
        self,
        scraper_name: str,
        duration: float,
        products_scraped: int = 0,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record a successful scraper run.

        Args:
            scraper_name: Name of the scraper
            duration: Duration of the run in seconds
            products_scraped: Number of products successfully scraped
            context: Additional context information
        """
        with self._lock:
            if scraper_name not in self._diagnostics:
                self.register_scraper(scraper_name)

            diagnostics = self._diagnostics[scraper_name]
            now = time.time()

            # Update run counts
            diagnostics.total_runs += 1
            diagnostics.successful_runs += 1
            diagnostics.recent_runs += 1
            diagnostics.recent_successes += 1

            # Update timestamps
            diagnostics.last_success_time = now
            diagnostics.updated_at = now

            # Update duration metrics
            self._update_duration_metrics(diagnostics, duration)

            # Calculate success rates
            diagnostics.success_rate = diagnostics.successful_runs / diagnostics.total_runs
            if diagnostics.recent_runs > 0:
                diagnostics.recent_success_rate = (
                    diagnostics.recent_successes / diagnostics.recent_runs
                )

            # Add to run history
            self._run_history[scraper_name].append(
                {
                    "timestamp": now,
                    "success": True,
                    "duration": duration,
                    "products_scraped": products_scraped,
                    "context": context or {},
                }
            )

            # Trim history to last 100 runs
            if len(self._run_history[scraper_name]) > 100:
                self._run_history[scraper_name] = self._run_history[scraper_name][-100:]

            # Reset circuit breaker failures on success
            diagnostics.circuit_breaker_failures = 0
            diagnostics.circuit_breaker_open = False

            # Update health status
            self._update_health_status(scraper_name)

            # Record success in failure analytics if available
            if self._failure_analytics:
                self._failure_analytics.record_success(
                    site_name=scraper_name,
                    duration=duration,
                    action="scrape_run",
                )

    def record_run_failure(
        self,
        scraper_name: str,
        duration: float | None = None,
        error_message: str | None = None,
        error_type: str | None = None,
        failure_type: FailureType | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record a failed scraper run.

        Args:
            scraper_name: Name of the scraper
            duration: Duration of the run in seconds (if known)
            error_message: Error message describing the failure
            error_type: Type/class of the error
            failure_type: FailureType classification
            context: Additional context information
        """
        with self._lock:
            if scraper_name not in self._diagnostics:
                self.register_scraper(scraper_name)

            diagnostics = self._diagnostics[scraper_name]
            now = time.time()

            # Update run counts
            diagnostics.total_runs += 1
            diagnostics.failed_runs += 1
            diagnostics.recent_runs += 1
            diagnostics.recent_failures += 1

            # Update timestamps and error info
            diagnostics.last_failure_time = now
            diagnostics.last_error_message = error_message
            diagnostics.last_error_type = error_type
            diagnostics.updated_at = now

            # Update duration if provided
            if duration:
                self._update_duration_metrics(diagnostics, duration)

            # Calculate success rates
            diagnostics.success_rate = diagnostics.successful_runs / diagnostics.total_runs
            if diagnostics.recent_runs > 0:
                diagnostics.recent_success_rate = (
                    diagnostics.recent_successes / diagnostics.recent_runs
                )

            # Track failure types
            failure_key = failure_type.value if failure_type else error_type or "unknown"
            diagnostics.failure_types[failure_key] = (
                diagnostics.failure_types.get(failure_key, 0) + 1
            )

            # Update most common failure
            if diagnostics.failure_types:
                diagnostics.most_common_failure = max(
                    diagnostics.failure_types.items(), key=lambda x: x[1]
                )[0]

            # Update circuit breaker status
            diagnostics.circuit_breaker_failures += 1
            if diagnostics.circuit_breaker_failures >= 5:
                diagnostics.circuit_breaker_open = True

            # Add to run history
            self._run_history[scraper_name].append(
                {
                    "timestamp": now,
                    "success": False,
                    "duration": duration,
                    "error_message": error_message,
                    "error_type": error_type,
                    "failure_type": failure_key,
                    "context": context or {},
                }
            )

            # Trim history
            if len(self._run_history[scraper_name]) > 100:
                self._run_history[scraper_name] = self._run_history[scraper_name][-100:]

            # Update health status
            self._update_health_status(scraper_name)

            # Record in failure analytics if available
            if self._failure_analytics and failure_type:
                self._failure_analytics.record_failure(
                    site_name=scraper_name,
                    failure_type=failure_type,
                    duration=duration,
                    action="scrape_run",
                    context=context,
                )

    def get_diagnostics(self, scraper_name: str) -> ScraperDiagnostics | None:
        """
        Get diagnostics for a specific scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            ScraperDiagnostics or None if not found
        """
        with self._lock:
            return self._diagnostics.get(scraper_name)

    def get_all_diagnostics(self) -> dict[str, ScraperDiagnostics]:
        """
        Get diagnostics for all registered scrapers.

        Returns:
            Dictionary mapping scraper names to their diagnostics
        """
        with self._lock:
            return dict(self._diagnostics)

    def get_health_status(self, scraper_name: str) -> HealthStatus:
        """
        Get the health status of a scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            HealthStatus enum value
        """
        with self._lock:
            diagnostics = self._diagnostics.get(scraper_name)
            if not diagnostics:
                return HealthStatus.UNKNOWN
            return diagnostics.status

    def get_health_summary(self) -> dict[str, Any]:
        """
        Get a summary of health across all scrapers.

        Returns:
            Dictionary with health summary statistics
        """
        with self._lock:
            total = len(self._diagnostics)
            if total == 0:
                return {
                    "total_scrapers": 0,
                    "healthy": 0,
                    "degraded": 0,
                    "unhealthy": 0,
                    "critical": 0,
                    "unknown": 0,
                    "overall_health_score": 1.0,
                    "scrapers_needing_attention": [],
                }

            status_counts = {
                HealthStatus.HEALTHY: 0,
                HealthStatus.DEGRADED: 0,
                HealthStatus.UNHEALTHY: 0,
                HealthStatus.CRITICAL: 0,
                HealthStatus.UNKNOWN: 0,
            }

            total_health_score = 0.0
            needing_attention = []

            for name, diag in self._diagnostics.items():
                status_counts[diag.status] += 1
                total_health_score += diag.health_score

                if diag.status in [
                    HealthStatus.DEGRADED,
                    HealthStatus.UNHEALTHY,
                    HealthStatus.CRITICAL,
                ]:
                    needing_attention.append(
                        {
                            "name": name,
                            "status": diag.status.value,
                            "health_score": diag.health_score,
                            "last_error": diag.last_error_message,
                        }
                    )

            # Sort by health score (worst first)
            needing_attention.sort(key=lambda x: float(x.get("health_score") or 1.0))

            return {
                "total_scrapers": total,
                "healthy": status_counts[HealthStatus.HEALTHY],
                "degraded": status_counts[HealthStatus.DEGRADED],
                "unhealthy": status_counts[HealthStatus.UNHEALTHY],
                "critical": status_counts[HealthStatus.CRITICAL],
                "unknown": status_counts[HealthStatus.UNKNOWN],
                "overall_health_score": round(total_health_score / total, 3),
                "scrapers_needing_attention": needing_attention,
            }

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """
        Get comprehensive statistics for all scrapers.
        Used by ReportGenerator.
        """
        from core.failure_analytics import get_failure_analytics

        analytics = get_failure_analytics()
        metrics = analytics.get_all_site_metrics()

        stats = {}
        for site, metric in metrics.items():
            successful_runs = metric.total_requests - metric.total_failures
            stats[site] = {
                "total_runs": metric.total_requests,
                "successful_runs": successful_runs,
                "failed_runs": metric.total_failures,
                "success_rate": metric.success_rate,
                "avg_duration": metric.avg_duration,
                "health_score": metric.health_score,
            }
        return stats

    def get_run_history(self, scraper_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get run history for a scraper.

        Args:
            scraper_name: Name of the scraper
            limit: Maximum number of records to return

        Returns:
            List of run history records (most recent first)
        """
        with self._lock:
            history = self._run_history.get(scraper_name, [])
            return list(reversed(history[-limit:]))

    def get_alerts(self, include_acknowledged: bool = False, limit: int = 50) -> list[HealthAlert]:
        """
        Get health alerts.

        Args:
            include_acknowledged: Whether to include acknowledged alerts
            limit: Maximum number of alerts to return

        Returns:
            List of HealthAlert objects (most recent first)
        """
        with self._lock:
            alerts = self._alerts
            if not include_acknowledged:
                alerts = [a for a in alerts if not a.acknowledged]
            return list(reversed(alerts[-limit:]))

    def acknowledge_alert(self, alert_index: int) -> bool:
        """
        Acknowledge an alert.

        Args:
            alert_index: Index of the alert in the alerts list

        Returns:
            True if acknowledged successfully
        """
        with self._lock:
            if 0 <= alert_index < len(self._alerts):
                self._alerts[alert_index].acknowledged = True
                return True
            return False

    def get_scraper_trend(self, scraper_name: str, hours: int = 24) -> dict[str, Any]:
        """
        Get performance trend for a scraper over time.

        Args:
            scraper_name: Name of the scraper
            hours: Number of hours to analyze

        Returns:
            Dictionary with trend information
        """
        with self._lock:
            history = self._run_history.get(scraper_name, [])
            if not history:
                return {
                    "scraper_name": scraper_name,
                    "period_hours": hours,
                    "runs": 0,
                    "trend": "stable",
                    "success_rate_change": 0.0,
                }

            cutoff = time.time() - (hours * 3600)
            recent = [r for r in history if r["timestamp"] >= cutoff]

            if len(recent) < 2:
                return {
                    "scraper_name": scraper_name,
                    "period_hours": hours,
                    "runs": len(recent),
                    "trend": "insufficient_data",
                    "success_rate_change": 0.0,
                }

            # Split into two halves for trend analysis
            midpoint = len(recent) // 2
            first_half = recent[:midpoint]
            second_half = recent[midpoint:]

            first_success_rate = (
                sum(1 for r in first_half if r["success"]) / len(first_half) if first_half else 0
            )
            second_success_rate = (
                sum(1 for r in second_half if r["success"]) / len(second_half) if second_half else 0
            )

            change = second_success_rate - first_success_rate

            if change > 0.1:
                trend = "improving"
            elif change < -0.1:
                trend = "declining"
            else:
                trend = "stable"

            return {
                "scraper_name": scraper_name,
                "period_hours": hours,
                "runs": len(recent),
                "successes": sum(1 for r in recent if r["success"]),
                "failures": sum(1 for r in recent if not r["success"]),
                "success_rate": round(sum(1 for r in recent if r["success"]) / len(recent), 3),
                "avg_duration": round(
                    sum(r.get("duration", 0) or 0 for r in recent) / len(recent), 2
                ),
                "trend": trend,
                "success_rate_change": round(change, 3),
            }

    def get_recommendations(self, scraper_name: str) -> list[str]:
        """
        Get actionable recommendations for improving scraper health.

        Args:
            scraper_name: Name of the scraper

        Returns:
            List of recommendation strings
        """
        with self._lock:
            diagnostics = self._diagnostics.get(scraper_name)
            if not diagnostics:
                return ["Register the scraper to get recommendations."]

            recommendations = []

            # Config recommendations
            if not diagnostics.config_valid:
                recommendations.append(f"Create configuration file at {diagnostics.config_path}")

            if diagnostics.config_valid and not diagnostics.has_test_skus:
                recommendations.append("Add test_skus to the configuration for automated testing")

            # Performance recommendations
            if diagnostics.success_rate < 0.5:
                recommendations.append(
                    "Critical: Success rate below 50%. Review error logs and "
                    "check for site changes or blocking."
                )

            if diagnostics.circuit_breaker_open:
                recommendations.append(
                    "Circuit breaker is open. Wait for cooldown or investigate and reset manually."
                )

            # Failure-specific recommendations
            if diagnostics.most_common_failure:
                failure = diagnostics.most_common_failure
                if failure in ["rate_limited", "RATE_LIMITED"]:
                    recommendations.append(
                        "High rate limiting. Increase delays between requests "
                        "and consider implementing request throttling."
                    )
                elif failure in ["captcha_detected", "CAPTCHA"]:
                    recommendations.append(
                        "Frequent CAPTCHA detection. Implement CAPTCHA solving "
                        "or adjust scraping patterns."
                    )
                elif failure in ["access_denied", "ACCESS_DENIED"]:
                    recommendations.append(
                        "Access denied errors. Rotate user agents, implement "
                        "session management, or use proxy rotation."
                    )
                elif failure in ["element_not_found", "ELEMENT_NOT_FOUND"]:
                    recommendations.append(
                        "Element not found errors. Verify selectors are up-to-date "
                        "with current site structure."
                    )
                elif failure in ["timeout", "TIMEOUT"]:
                    recommendations.append(
                        "Timeout errors. Increase timeout settings or check network connectivity."
                    )

            # Duration recommendations
            if diagnostics.avg_duration_seconds > 300:  # > 5 minutes
                recommendations.append(
                    f"Average run duration is {diagnostics.avg_duration_seconds:.0f}s. "
                    "Consider optimizing selectors or reducing page loads."
                )

            if not recommendations:
                recommendations.append("Scraper is performing well. Continue monitoring.")

            return recommendations

    def _update_duration_metrics(self, diagnostics: ScraperDiagnostics, duration: float) -> None:
        """Update duration metrics with a new data point."""
        if diagnostics.total_runs == 1:
            diagnostics.avg_duration_seconds = duration
            diagnostics.min_duration_seconds = duration
            diagnostics.max_duration_seconds = duration
        else:
            # Rolling average
            diagnostics.avg_duration_seconds = (
                (diagnostics.avg_duration_seconds * (diagnostics.total_runs - 1)) + duration
            ) / diagnostics.total_runs
            diagnostics.min_duration_seconds = min(diagnostics.min_duration_seconds, duration)
            diagnostics.max_duration_seconds = max(diagnostics.max_duration_seconds, duration)

    def _update_health_status(self, scraper_name: str) -> None:
        """Update the health status based on current metrics."""
        diagnostics = self._diagnostics.get(scraper_name)
        if not diagnostics:
            return

        # Calculate health score based on multiple factors
        factors = []

        # Success rate factor (weighted heavily)
        if diagnostics.total_runs > 0:
            factors.append(diagnostics.success_rate * 0.5)

            # Recent success rate factor
            if diagnostics.recent_runs > 0:
                factors.append(diagnostics.recent_success_rate * 0.3)
            else:
                factors.append(0.3)  # No recent data, neutral

            # Circuit breaker factor
            if diagnostics.circuit_breaker_open:
                factors.append(0.0)  # Severely penalize open circuit
            else:
                cb_penalty = min(diagnostics.circuit_breaker_failures / 5, 1.0)
                factors.append((1.0 - cb_penalty) * 0.2)
        else:
            # No runs yet
            factors = [1.0]  # Assume healthy until proven otherwise

        # Calculate final health score
        health_score = sum(factors)
        diagnostics.health_score = round(min(max(health_score, 0.0), 1.0), 3)

        # Determine status from health score
        previous_status = diagnostics.status

        if health_score >= self.HEALTHY_THRESHOLD:
            diagnostics.status = HealthStatus.HEALTHY
        elif health_score >= self.DEGRADED_THRESHOLD:
            diagnostics.status = HealthStatus.DEGRADED
        elif health_score >= self.UNHEALTHY_THRESHOLD:
            diagnostics.status = HealthStatus.UNHEALTHY
        else:
            diagnostics.status = HealthStatus.CRITICAL

        # Generate alerts on status change
        if previous_status != diagnostics.status:
            self._generate_status_change_alert(scraper_name, previous_status, diagnostics.status)

    def _generate_status_change_alert(
        self,
        scraper_name: str,
        old_status: HealthStatus,
        new_status: HealthStatus,
    ) -> None:
        """Generate an alert when scraper status changes."""
        # Determine alert type and severity
        status_severity = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.UNKNOWN: 1,
            HealthStatus.DEGRADED: 2,
            HealthStatus.UNHEALTHY: 3,
            HealthStatus.CRITICAL: 4,
        }

        old_severity = status_severity.get(old_status, 1)
        new_severity = status_severity.get(new_status, 1)

        if new_severity > old_severity:
            # Health degraded
            if new_status == HealthStatus.CRITICAL:
                alert_type = "critical"
                severity = "critical"
                message = (
                    f"Scraper '{scraper_name}' is in CRITICAL state. Immediate attention required."
                )
            elif new_status == HealthStatus.UNHEALTHY:
                alert_type = "unhealthy"
                severity = "error"
                message = f"Scraper '{scraper_name}' is UNHEALTHY. High failure rate detected."
            else:
                alert_type = "degraded"
                severity = "warning"
                message = f"Scraper '{scraper_name}' is DEGRADED. Performance has declined."
        else:
            # Health improved
            alert_type = "recovered"
            severity = "info"
            message = f"Scraper '{scraper_name}' has recovered to {new_status.value} status."

        alert = HealthAlert(
            scraper_name=scraper_name,
            alert_type=alert_type,
            message=message,
            severity=severity,
        )

        self._alerts.append(alert)

        # Trim alerts to last 500
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]

        # Call alert callback if registered
        if self._alert_callback:
            try:
                self._alert_callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        logger.info(f"Health alert: {message}")

    def _background_monitor(self) -> None:
        """Background thread for periodic health checks."""
        while self._monitoring_active:
            try:
                time.sleep(300)  # Run every 5 minutes
                self._periodic_health_check()
            except Exception as e:
                logger.error(f"Background monitor error: {e}")

    def _periodic_health_check(self) -> None:
        """Perform periodic health checks on all scrapers."""
        with self._lock:
            now = time.time()
            one_hour_ago = now - 3600

            for scraper_name, diagnostics in self._diagnostics.items():
                # Reset recent counters if no recent activity
                if diagnostics.last_run_time and diagnostics.last_run_time < one_hour_ago:
                    # Decay recent counters
                    diagnostics.recent_runs = max(0, diagnostics.recent_runs - 1)
                    diagnostics.recent_successes = max(0, diagnostics.recent_successes - 1)
                    diagnostics.recent_failures = max(0, diagnostics.recent_failures - 1)

                    # Recalculate recent success rate
                    if diagnostics.recent_runs > 0:
                        diagnostics.recent_success_rate = (
                            diagnostics.recent_successes / diagnostics.recent_runs
                        )

                    # Update health status
                    self._update_health_status(scraper_name)

    def reset_scraper_stats(self, scraper_name: str) -> bool:
        """
        Reset statistics for a scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            True if reset successfully
        """
        with self._lock:
            if scraper_name not in self._diagnostics:
                return False

            # Reset diagnostics but keep config info
            old_diag = self._diagnostics[scraper_name]
            new_diag = ScraperDiagnostics(
                scraper_name=scraper_name,
                config_valid=old_diag.config_valid,
                config_path=old_diag.config_path,
                has_test_skus=old_diag.has_test_skus,
            )
            self._diagnostics[scraper_name] = new_diag
            self._run_history[scraper_name] = []

            logger.info(f"Reset stats for scraper: {scraper_name}")
            return True

    def reset_circuit_breaker(self, scraper_name: str) -> bool:
        """
        Reset the circuit breaker for a scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            True if reset successfully
        """
        with self._lock:
            diagnostics = self._diagnostics.get(scraper_name)
            if not diagnostics:
                return False

            diagnostics.circuit_breaker_open = False
            diagnostics.circuit_breaker_failures = 0
            diagnostics.updated_at = time.time()

            logger.info(f"Reset circuit breaker for scraper: {scraper_name}")
            return True

    def format_diagnostics_report(self, scraper_name: str) -> str:
        """
        Generate a human-readable diagnostics report.

        Args:
            scraper_name: Name of the scraper

        Returns:
            Formatted report string
        """
        diagnostics = self.get_diagnostics(scraper_name)
        if not diagnostics:
            return f"No diagnostics available for scraper: {scraper_name}"

        lines = [
            f"=== Diagnostics Report: {scraper_name} ===",
            "",
            f"Status: {diagnostics.status.value.upper()}",
            f"Health Score: {diagnostics.health_score:.1%}",
            "",
            "--- Performance Metrics ---",
            f"Total Runs: {diagnostics.total_runs}",
            f"Success Rate: {diagnostics.success_rate:.1%}",
            f"Average Duration: {diagnostics.avg_duration_seconds:.1f}s",
            "",
            "--- Recent Activity (24h) ---",
            f"Recent Runs: {diagnostics.recent_runs}",
            f"Recent Success Rate: {diagnostics.recent_success_rate:.1%}",
            "",
        ]

        if diagnostics.last_run_time:
            last_run = datetime.fromtimestamp(diagnostics.last_run_time)
            lines.append(f"Last Run: {last_run.strftime('%Y-%m-%d %H:%M:%S')}")

        if diagnostics.last_error_message:
            lines.extend(
                [
                    "",
                    "--- Last Error ---",
                    f"Type: {diagnostics.last_error_type or 'Unknown'}",
                    f"Message: {diagnostics.last_error_message[:200]}",
                ]
            )

        if diagnostics.circuit_breaker_open:
            lines.extend(
                [
                    "",
                    "CIRCUIT BREAKER IS OPEN",
                    f"Consecutive failures: {diagnostics.circuit_breaker_failures}",
                ]
            )

        recommendations = self.get_recommendations(scraper_name)
        if recommendations:
            lines.extend(
                [
                    "",
                    "--- Recommendations ---",
                ]
            )
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec}")

        return "\n".join(lines)

    def shutdown(self) -> None:
        """Shutdown the health monitor."""
        logger.info("Shutting down ScraperHealthMonitor")
        self._monitoring_active = False


# Singleton instance for global access
_health_monitor_instance: ScraperHealthMonitor | None = None


def get_health_monitor(
    failure_analytics: FailureAnalytics | None = None,
) -> ScraperHealthMonitor:
    """
    Get or create the global health monitor instance.

    Args:
        failure_analytics: Optional FailureAnalytics instance

    Returns:
        ScraperHealthMonitor instance
    """
    global _health_monitor_instance
    if _health_monitor_instance is None:
        _health_monitor_instance = ScraperHealthMonitor(failure_analytics=failure_analytics)
    return _health_monitor_instance
