"""
AI Fallback Chain Manager.

Implements tiered fallback strategy: AI → Traditional → Manual Queue.
Handles failures gracefully and tracks fallback events.
"""

from __future__ import annotations

import logging
from typing import Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class FallbackTier(Enum):
    """Fallback tiers in order of preference."""

    AI = "ai"
    TRADITIONAL = "traditional"
    MANUAL = "manual"


@dataclass
class FallbackEvent:
    """Record of a fallback event."""

    scraper_name: str
    from_tier: FallbackTier
    to_tier: FallbackTier
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class AIFallbackManager:
    """Manages fallback chain for AI scrapers.

    Fallback chain: AI → Traditional → Manual Queue

    Usage:
        manager = AIFallbackManager()
        result = await manager.execute_with_fallback(
            scraper_config=config,
            execution_context=ctx
        )
    """

    MAX_ATTEMPTS_PER_TIER = 2

    def __init__(self):
        self.fallback_events: list[FallbackEvent] = []
        self._attempt_counts: dict[str, dict[FallbackTier, int]] = {}

    async def execute_with_fallback(self, scraper_config: Any, execution_context: Any) -> dict[str, Any]:
        """Execute scraper with automatic fallback on failure.

        Args:
            scraper_config: Scraper configuration
            execution_context: Execution context

        Returns:
            Extraction result or fallback status
        """
        scraper_name = getattr(scraper_config, "name", "unknown")

        # Check if AI is enabled for this scraper
        scraper_type = getattr(scraper_config, "scraper_type", "static")

        if scraper_type == "agentic":
            # Try AI first
            result = await self._try_ai_extraction(scraper_config, execution_context)

            if result.get("success"):
                return result

            # AI failed, try traditional
            if self._should_fallback(scraper_name, FallbackTier.AI, FallbackTier.TRADITIONAL):
                self._record_fallback(scraper_name, FallbackTier.AI, FallbackTier.TRADITIONAL, result.get("error", "Unknown"))
                result = await self._try_traditional_extraction(scraper_config, execution_context)

                if result.get("success"):
                    return result
        else:
            # Try traditional first for static scrapers
            result = await self._try_traditional_extraction(scraper_config, execution_context)

            if result.get("success"):
                return result

        # Both AI and Traditional failed, queue for manual
        if self._should_fallback(scraper_name, FallbackTier.TRADITIONAL, FallbackTier.MANUAL):
            self._record_fallback(scraper_name, FallbackTier.TRADITIONAL, FallbackTier.MANUAL, result.get("error", "Unknown"))
            return await self._queue_for_manual(scraper_config, execution_context)

        return result

    async def _try_ai_extraction(self, scraper_config: Any, execution_context: Any) -> dict[str, Any]:
        """Attempt AI extraction."""
        try:
            # Import and execute AI workflow
            from scrapers.executor.workflow_executor import WorkflowExecutor

            executor = WorkflowExecutor(scraper_config, execution_context)
            result = await executor.execute()

            if result and not result.get("error"):
                return {"success": True, "data": result, "tier": "ai"}

            return {"success": False, "error": result.get("error", "AI extraction failed"), "tier": "ai"}

        except Exception as e:
            logger.error(f"AI extraction failed: {e}")
            return {"success": False, "error": str(e), "tier": "ai"}

    async def _try_traditional_extraction(self, scraper_config: Any, execution_context: Any) -> dict[str, Any]:
        """Attempt traditional extraction."""
        try:
            # Use static workflow (CSS selectors)
            from scrapers.executor.workflow_executor import WorkflowExecutor

            # Temporarily set scraper_type to static
            original_type = getattr(scraper_config, "scraper_type", None)
            scraper_config.scraper_type = "static"

            executor = WorkflowExecutor(scraper_config, execution_context)
            result = await executor.execute()

            # Restore original type
            if original_type:
                scraper_config.scraper_type = original_type

            if result and not result.get("error"):
                return {"success": True, "data": result, "tier": "traditional"}

            return {"success": False, "error": result.get("error", "Traditional extraction failed"), "tier": "traditional"}

        except Exception as e:
            logger.error(f"Traditional extraction failed: {e}")
            return {"success": False, "error": str(e), "tier": "traditional"}

    async def _queue_for_manual(self, scraper_config: Any, execution_context: Any) -> dict[str, Any]:
        """Queue for manual extraction."""
        logger.warning(f"Queueing {scraper_config.name} for manual extraction")

        # Store in context for later processing
        execution_context.results["manual_extraction_needed"] = True
        execution_context.results["manual_extraction_reason"] = "AI and traditional extraction failed"

        return {"success": False, "tier": "manual", "status": "queued_for_manual", "message": "Extraction queued for manual processing"}

    def _should_fallback(self, scraper_name: str, from_tier: FallbackTier, to_tier: FallbackTier) -> bool:
        """Check if fallback should be attempted."""
        if scraper_name not in self._attempt_counts:
            self._attempt_counts[scraper_name] = {}

        current_attempts = self._attempt_counts[scraper_name].get(from_tier, 0)

        if current_attempts >= self.MAX_ATTEMPTS_PER_TIER:
            logger.warning(f"Max attempts reached for {scraper_name} at {from_tier.value} tier")
            return False

        self._attempt_counts[scraper_name][from_tier] = current_attempts + 1
        return True

    def _record_fallback(self, scraper_name: str, from_tier: FallbackTier, to_tier: FallbackTier, reason: str, details: dict[str, Any] | None = None):
        """Record a fallback event."""
        event = FallbackEvent(scraper_name=scraper_name, from_tier=from_tier, to_tier=to_tier, reason=reason, details=details or {})
        self.fallback_events.append(event)

        logger.info(f"Fallback triggered for {scraper_name}: {from_tier.value} → {to_tier.value} (reason: {reason})")

    def get_fallback_stats(self) -> dict[str, Any]:
        """Get fallback statistics."""
        if not self.fallback_events:
            return {"total_fallbacks": 0, "by_tier": {}, "by_scraper": {}}

        by_tier = {}
        by_scraper = {}

        for event in self.fallback_events:
            tier_key = f"{event.from_tier.value}_to_{event.to_tier.value}"
            by_tier[tier_key] = by_tier.get(tier_key, 0) + 1

            by_scraper[event.scraper_name] = by_scraper.get(event.scraper_name, 0) + 1

        return {"total_fallbacks": len(self.fallback_events), "by_tier": by_tier, "by_scraper": by_scraper}


# Convenience function
async def execute_with_fallback(scraper_config: Any, execution_context: Any) -> dict[str, Any]:
    """Standalone function for fallback execution."""
    manager = AIFallbackManager()
    return await manager.execute_with_fallback(scraper_config, execution_context)
