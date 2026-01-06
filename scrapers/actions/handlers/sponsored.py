from __future__ import annotations

import logging
from typing import Any

# Selenium imports removed - using executor's find_elements_safe
# from selenium.webdriver.common.by import By
from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("check_sponsored")
class CheckSponsoredAction(BaseAction):
    """Action to check if an element is sponsored/ad content."""

    def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        result_field = params.get("result_field", "is_sponsored")

        if not selector:
            self.executor.results[result_field] = False
            return

        try:
            elements = self.executor.find_elements_safe(selector)
            is_sponsored = len(elements) > 0
            self.executor.results[result_field] = is_sponsored
            logger.debug(f"Checked sponsored content ({selector}): {is_sponsored}")
        except Exception:
            self.executor.results[result_field] = False
