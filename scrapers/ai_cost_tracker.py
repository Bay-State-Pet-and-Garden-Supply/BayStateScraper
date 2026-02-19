"""
AI extraction cost tracking and budget enforcement.

Tracks per-extraction costs and enforces hard limits to prevent
runaway API spending. Includes circuit breaker for repeated overruns.
"""

import logging
from typing import Any
from dataclasses import dataclass, field
from collections import defaultdict

from scrapers.ai_metrics import (
    record_ai_extraction,
    record_ai_fallback,
    set_circuit_breaker,
)

logger = logging.getLogger(__name__)

# Cost limits configuration
MAX_COST_PER_PAGE = 0.15  # USD - hard limit before fallback
COST_WARNING_THRESHOLD = 0.10  # USD - warning alert
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive overruns before disabling


@dataclass
class ExtractionCost:
    """Cost data for a single extraction."""

    input_tokens: int
    output_tokens: int
    model: str
    cost_usd: float
    timestamp: str = field(default_factory=lambda: __import__("datetime").datetime.now().isoformat())


class AICostTracker:
    """Tracks AI extraction costs and enforces budget limits.

    Usage:
        tracker = AICostTracker()

        # Track an extraction
        tracker.track_extraction(
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o-mini"
        )

        # Check if cost is within budget
        if tracker.check_cost_budget(current_cost=0.08):
            continue_extraction()
        else:
            trigger_fallback()
    """

    # OpenAI pricing per 1K tokens (as of 2024)
    PRICING = {
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    }

    def __init__(self):
        self.extractions: list[ExtractionCost] = []
        self._circuit_breaker_counts: dict[str, int] = defaultdict(int)
        self._total_cost_usd: float = 0.0

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a given model and token usage.

        Args:
            model: Model name (e.g., "gpt-4o-mini")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        # Normalize model name
        model_key = model.lower()
        if model_key not in self.PRICING:
            # Default to gpt-4o-mini pricing if unknown
            logger.warning(f"Unknown model '{model}', using gpt-4o-mini pricing")
            model_key = "gpt-4o-mini"

        pricing = self.PRICING[model_key]
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]

        return input_cost + output_cost

    def track_extraction(self, input_tokens: int, output_tokens: int, model: str, scraper_name: str = "default") -> ExtractionCost:
        """Track an extraction and return cost data.

        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens generated
            model: Model name used
            scraper_name: Name of the scraper for circuit breaker tracking

        Returns:
            ExtractionCost object with cost details
        """
        cost_usd = self.calculate_cost(model, input_tokens, output_tokens)

        extraction = ExtractionCost(input_tokens=input_tokens, output_tokens=output_tokens, model=model, cost_usd=cost_usd)

        self.extractions.append(extraction)
        self._total_cost_usd += cost_usd

        # Check if this extraction exceeded limits
        exceeded_limit = cost_usd > MAX_COST_PER_PAGE
        if exceeded_limit:
            self._circuit_breaker_counts[scraper_name] += 1
            logger.warning(
                f"Cost exceeded threshold: ${cost_usd:.4f} > ${MAX_COST_PER_PAGE} "
                f"for scraper '{scraper_name}' "
                f"(strike {self._circuit_breaker_counts[scraper_name]}/{CIRCUIT_BREAKER_THRESHOLD})"
            )
            record_ai_fallback(scraper_name, f"high_cost:${cost_usd:.4f}")
        else:
            # Reset circuit breaker on successful extraction
            if scraper_name in self._circuit_breaker_counts:
                del self._circuit_breaker_counts[scraper_name]

        record_ai_extraction(
            scraper_name=scraper_name,
            success=not exceeded_limit,
            cost_usd=cost_usd,
            duration_seconds=0.0,
            anti_bot_detected=False,
        )

        if self._circuit_breaker_counts.get(scraper_name, 0) >= CIRCUIT_BREAKER_THRESHOLD:
            set_circuit_breaker(scraper_name, True)

        return extraction

    def check_cost_budget(self, current_cost: float, scraper_name: str = "default") -> bool:
        """Check if current cost is within budget.

        Returns False if:
        - Cost exceeds MAX_COST_PER_PAGE
        - Circuit breaker threshold reached

        Args:
            current_cost: Current extraction cost in USD
            scraper_name: Name of the scraper for circuit breaker tracking

        Returns:
            True if within budget, False if should trigger fallback
        """
        # Check hard limit
        if current_cost > MAX_COST_PER_PAGE:
            logger.warning(f"Cost exceeded hard limit: ${current_cost:.4f} > ${MAX_COST_PER_PAGE}")
            return False

        # Check circuit breaker
        if self._circuit_breaker_counts[scraper_name] >= CIRCUIT_BREAKER_THRESHOLD:
            logger.error(f"Circuit breaker activated for scraper '{scraper_name}' after {CIRCUIT_BREAKER_THRESHOLD} consecutive overruns")
            return False

        return True

    def is_circuit_breaker_active(self, scraper_name: str = "default") -> bool:
        """Check if circuit breaker is active for a scraper."""
        return self._circuit_breaker_counts[scraper_name] >= CIRCUIT_BREAKER_THRESHOLD

    def get_cost_summary(self) -> dict[str, Any]:
        """Get summary of all tracked costs.

        Returns:
            Dictionary with cost statistics
        """
        if not self.extractions:
            return {
                "total_extractions": 0,
                "total_cost_usd": 0.0,
                "average_cost_usd": 0.0,
                "max_cost_usd": 0.0,
                "min_cost_usd": 0.0,
            }

        costs = [e.cost_usd for e in self.extractions]
        return {
            "total_extractions": len(self.extractions),
            "total_cost_usd": self._total_cost_usd,
            "average_cost_usd": self._total_cost_usd / len(self.extractions),
            "max_cost_usd": max(costs),
            "min_cost_usd": min(costs),
        }

    def reset_circuit_breaker(self, scraper_name: str = "default"):
        """Reset circuit breaker for a scraper (e.g., after manual intervention)."""
        if scraper_name in self._circuit_breaker_counts:
            del self._circuit_breaker_counts[scraper_name]
            logger.info(f"Circuit breaker reset for scraper '{scraper_name}'")


# Convenience function for standalone usage
def check_cost_budget(current_cost: float, scraper_name: str = "default") -> bool:
    """Standalone function to check if cost is within budget.

    This is a convenience function for use in actions without
    instantiating AICostTracker.

    Args:
        current_cost: Current extraction cost in USD
        scraper_name: Name of the scraper

    Returns:
        True if within budget, False if should trigger fallback
    """
    tracker = AICostTracker()
    return tracker.check_cost_budget(current_cost, scraper_name)
