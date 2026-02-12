from __future__ import annotations
import asyncio

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("check_sponsored")
class CheckSponsoredAction(BaseAction):
    """Action to check if an element is sponsored/ad content."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        result_field = params.get("result_field", "is_sponsored")

        if not selector:
            self.ctx.results[result_field] = False
            return

        try:
            elements = self.ctx.find_elements_safe(selector)
            is_sponsored = len(elements) > 0
            self.ctx.results[result_field] = is_sponsored
            logger.debug(f"Checked sponsored content ({selector}): {is_sponsored}")
        except Exception:
            self.ctx.results[result_field] = False
