"""
AI scraper metrics and monitoring for Prometheus.

Provides metrics collection and alerting for AI-powered scrapers.
Integrates with the existing AICostTracker for cost monitoring.
"""

import logging
import time
from typing import Any
from dataclasses import dataclass
from collections import defaultdict, deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Alert thresholds
HIGH_COST_THRESHOLD = 0.10  # USD per page
LOW_SUCCESS_RATE_THRESHOLD = 0.70  # 70%
LOW_SUCCESS_RATE_WINDOW = timedelta(hours=1)
REPEATED_FAILURES_THRESHOLD = 3


@dataclass
class Alert:
    """Represents an alert condition."""

    name: str
    severity: str  # info, warning, critical
    message: str
    timestamp: datetime
    metadata: dict[str, Any]


class AIMetricsCollector:
    """Collects metrics for AI scraper monitoring.

    Tracks:
    - Extraction counts and costs
    - Success/failure rates
    - Circuit breaker status
    - Fallback frequency
    - Per-site performance
    """

    def __init__(self):
        # Counters
        self._extraction_count = 0
        self._extraction_success_count = 0
        self._extraction_failure_count = 0
        self._fallback_count = 0
        self._total_cost_usd = 0.0

        # Per-site tracking
        self._site_extractions: dict[str, dict] = defaultdict(
            lambda: {
                "count": 0,
                "success": 0,
                "failure": 0,
                "total_cost": 0.0,
            }
        )

        # Sliding window for success rate calculation
        self._extraction_history: deque[tuple[datetime, bool]] = deque(maxlen=1000)

        # Alert history
        self._alerts: list[Alert] = []
        self._alert_suppression: dict[str, datetime] = {}

        # Circuit breaker tracking
        self._circuit_breaker_active: dict[str, bool] = {}
        self._consecutive_failures: dict[str, int] = defaultdict(int)

    def record_extraction(
        self,
        scraper_name: str,
        success: bool,
        cost_usd: float,
        duration_seconds: float,
        anti_bot_detected: bool = False,
    ) -> None:
        """Record an AI extraction attempt.

        Args:
            scraper_name: Name of the scraper
            success: Whether extraction succeeded
            cost_usd: Cost of the extraction
            duration_seconds: Duration of extraction
            anti_bot_detected: Whether anti-bot was detected
        """
        now = datetime.now()

        # Update global counters
        self._extraction_count += 1
        self._total_cost_usd += cost_usd

        if success:
            self._extraction_success_count += 1
            self._consecutive_failures[scraper_name] = 0
        else:
            self._extraction_failure_count += 1
            self._consecutive_failures[scraper_name] += 1

        # Update per-site tracking
        site_stats = self._site_extractions[scraper_name]
        site_stats["count"] += 1
        site_stats["total_cost"] += cost_usd
        if success:
            site_stats["success"] += 1
        else:
            site_stats["failure"] += 1

        # Add to sliding window
        self._extraction_history.append((now, success))

        # Check for alerts
        self._check_alerts(scraper_name, cost_usd, success, anti_bot_detected)

    def record_fallback(self, scraper_name: str, reason: str) -> None:
        """Record a fallback to static scraping.

        Args:
            scraper_name: Name of the scraper
            reason: Reason for fallback (e.g., "high_cost", "circuit_breaker", "anti_bot")
        """
        self._fallback_count += 1
        logger.info(f"Fallback triggered for {scraper_name}: {reason}")

    def set_circuit_breaker(self, scraper_name: str, active: bool) -> None:
        """Set circuit breaker status for a scraper.

        Args:
            scraper_name: Name of the scraper
            active: Whether circuit breaker is active
        """
        was_active = self._circuit_breaker_active.get(scraper_name, False)
        self._circuit_breaker_active[scraper_name] = active

        if active and not was_active:
            self._create_alert(
                name="circuit_breaker_activated",
                severity="warning",
                message=f"Circuit breaker activated for {scraper_name}",
                scraper_name=scraper_name,
            )

    def get_success_rate(self, window_minutes: int = 60) -> float:
        """Calculate success rate over a time window.

        Args:
            window_minutes: Time window in minutes

        Returns:
            Success rate as a float between 0 and 1
        """
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        recent = [(ts, success) for ts, success in self._extraction_history if ts > cutoff]

        if not recent:
            return 1.0  # Default to 100% if no data

        successes = sum(1 for _, success in recent if success)
        return successes / len(recent)

    def get_site_success_rate(self, scraper_name: str) -> float:
        """Get success rate for a specific scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            Success rate as a float between 0 and 1
        """
        stats = self._site_extractions[scraper_name]
        total = stats["success"] + stats["failure"]
        if total == 0:
            return 1.0
        return stats["success"] / total

    def _check_alerts(
        self,
        scraper_name: str,
        cost_usd: float,
        success: bool,
        anti_bot_detected: bool,
    ) -> None:
        """Check for alert conditions and create alerts."""
        # High cost alert
        if cost_usd > HIGH_COST_THRESHOLD:
            self._create_alert(
                name="high_cost_per_page",
                severity="warning",
                message=f"High cost per page: ${cost_usd:.4f} > ${HIGH_COST_THRESHOLD}",
                scraper_name=scraper_name,
                cost_usd=cost_usd,
            )

        # Low success rate alert
        success_rate = self.get_site_success_rate(scraper_name)
        if success_rate < LOW_SUCCESS_RATE_THRESHOLD:
            self._create_alert(
                name="low_success_rate",
                severity="critical",
                message=f"Low success rate for {scraper_name}: {success_rate:.1%} < {LOW_SUCCESS_RATE_THRESHOLD:.1%}",
                scraper_name=scraper_name,
                success_rate=success_rate,
            )

        # Repeated failures alert
        if self._consecutive_failures[scraper_name] >= REPEATED_FAILURES_THRESHOLD:
            self._create_alert(
                name="repeated_failures",
                severity="warning",
                message=f"Repeated failures for {scraper_name}: {self._consecutive_failures[scraper_name]} consecutive",
                scraper_name=scraper_name,
                consecutive_failures=self._consecutive_failures[scraper_name],
            )

        # Anti-bot blocked alert
        if anti_bot_detected:
            self._create_alert(
                name="anti_bot_blocked",
                severity="info",
                message=f"Anti-bot/CAPTCHA detected for {scraper_name}",
                scraper_name=scraper_name,
            )

    def _create_alert(self, name: str, severity: str, message: str, **metadata) -> None:
        """Create an alert with suppression to prevent spam."""
        # Suppress duplicate alerts for 5 minutes
        alert_key = f"{name}:{metadata.get('scraper_name', 'global')}"
        now = datetime.now()

        if alert_key in self._alert_suppression:
            if now - self._alert_suppression[alert_key] < timedelta(minutes=5):
                return

        self._alert_suppression[alert_key] = now

        alert = Alert(
            name=name,
            severity=severity,
            message=message,
            timestamp=now,
            metadata=metadata,
        )
        self._alerts.append(alert)

        # Log the alert
        log_method = getattr(logger, severity, logger.info)
        log_method(f"[ALERT] {name}: {message}")

    def get_metrics(self) -> dict[str, Any]:
        """Get all metrics for Prometheus export.

        Returns:
            Dictionary of metrics
        """
        total = self._extraction_success_count + self._extraction_failure_count
        success_rate = self._extraction_success_count / total if total > 0 else 1.0

        return {
            # Global counters
            "ai_extraction_count": self._extraction_count,
            "ai_extraction_success": self._extraction_success_count,
            "ai_extraction_failure": self._extraction_failure_count,
            "ai_success_rate": success_rate,
            "ai_cost_total": self._total_cost_usd,
            "ai_fallback_count": self._fallback_count,
            # Per-site metrics
            "ai_site_metrics": dict(self._site_extractions),
            # Circuit breaker status
            "ai_circuit_breaker_active": dict(self._circuit_breaker_active),
            # Recent alerts
            "ai_recent_alerts": [
                {
                    "name": a.name,
                    "severity": a.severity,
                    "message": a.message,
                    "timestamp": a.timestamp.isoformat(),
                    "metadata": a.metadata,
                }
                for a in self._alerts[-10:]  # Last 10 alerts
            ],
        }

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        # Counter metrics
        lines.append(f"# HELP ai_extraction_count Total number of AI extractions")
        lines.append(f"# TYPE ai_extraction_count counter")
        lines.append(f"ai_extraction_count {{}} {self._extraction_count}")

        lines.append(f"# HELP ai_extraction_success Total number of successful AI extractions")
        lines.append(f"# TYPE ai_extraction_success counter")
        lines.append(f"ai_extraction_success {{}} {self._extraction_success_count}")

        lines.append(f"# HELP ai_extraction_failure Total number of failed AI extractions")
        lines.append(f"# TYPE ai_extraction_failure counter")
        lines.append(f"ai_extraction_failure {{}} {self._extraction_failure_count}")

        lines.append(f"# HELP ai_cost_total Total cost of AI extractions in USD")
        lines.append(f"# TYPE ai_cost_total counter")
        lines.append(f"ai_cost_total {{}} {self._total_cost_usd:.6f}")

        lines.append(f"# HELP ai_fallback_count Total number of fallback to static scraping")
        lines.append(f"# TYPE ai_fallback_count counter")
        lines.append(f"ai_fallback_count {{}} {self._fallback_count}")

        # Gauge metrics
        lines.append(f"# HELP ai_success_rate Current success rate")
        lines.append(f"# TYPE ai_success_rate gauge")
        lines.append(f"ai_success_rate {{}} {self.get_success_rate():.4f}")

        # Per-site metrics
        for site, stats in self._site_extractions.items():
            total = stats["success"] + stats["failure"]
            site_success_rate = stats["success"] / total if total > 0 else 1.0

            lines.append(f'ai_site_extractions{{site="{site}"}} {stats["count"]}')
            lines.append(f'ai_site_success_rate{{site="{site}"}} {site_success_rate:.4f}')
            lines.append(f'ai_site_cost_total{{site="{site}"}} {stats["total_cost"]:.6f}')

        # Circuit breaker status
        for site, active in self._circuit_breaker_active.items():
            status = 1 if active else 0
            lines.append(f'ai_circuit_breaker_active{{site="{site}"}} {status}')

        return "\n".join(lines) + "\n"


# Global metrics collector instance
_metrics_collector = AIMetricsCollector()


def get_metrics_collector() -> AIMetricsCollector:
    """Get the global metrics collector instance."""
    return _metrics_collector


def record_ai_extraction(
    scraper_name: str,
    success: bool,
    cost_usd: float,
    duration_seconds: float,
    anti_bot_detected: bool = False,
) -> None:
    """Convenience function to record an extraction.

    Args:
        scraper_name: Name of the scraper
        success: Whether extraction succeeded
        cost_usd: Cost of the extraction
        duration_seconds: Duration of extraction
        anti_bot_detected: Whether anti-bot was detected
    """
    _metrics_collector.record_extraction(
        scraper_name=scraper_name,
        success=success,
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        anti_bot_detected=anti_bot_detected,
    )


def record_ai_fallback(scraper_name: str, reason: str) -> None:
    """Convenience function to record a fallback.

    Args:
        scraper_name: Name of the scraper
        reason: Reason for fallback
    """
    _metrics_collector.record_fallback(scraper_name, reason)


def set_circuit_breaker(scraper_name: str, active: bool) -> None:
    """Convenience function to set circuit breaker status.

    Args:
        scraper_name: Name of the scraper
        active: Whether circuit breaker is active
    """
    _metrics_collector.set_circuit_breaker(scraper_name, active)
