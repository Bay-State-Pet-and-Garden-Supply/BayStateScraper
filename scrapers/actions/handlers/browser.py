from __future__ import annotations

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("configure_browser")
class ConfigureBrowserAction(BaseAction):
    """Action to configure browser settings dynamically."""

    def execute(self, params: dict[str, Any]) -> None:
        block_resources = params.get("block_resources", [])

        if not block_resources:
            return

        # Check for Playwright backend
        is_playwright = False
        try:
            from utils.scraping.playwright_browser import (
                SyncPlaywrightScraperBrowser,
            )

            if isinstance(self.executor.browser, SyncPlaywrightScraperBrowser):
                is_playwright = True
        except ImportError:
            pass

        if is_playwright:
            try:
                # Playwright resource blocking
                for pattern in block_resources:
                    # Handle patterns if necessary, or pass directly
                    self.executor.browser.page.route(pattern, lambda route: route.abort())
                logger.info(f"Blocked resources (Playwright): {block_resources}")
            except Exception as e:
                logger.warning(f"Failed to block resources (Playwright): {e}")

        # Selenium fallback
        elif (
            hasattr(self.executor.browser, "driver")
            and self.executor.browser.driver.name == "chrome"
        ):
            try:
                self.executor.browser.driver.execute_cdp_cmd(
                    "Network.setBlockedURLs", {"urls": block_resources}
                )
                self.executor.browser.driver.execute_cdp_cmd("Network.enable", {})
                logger.info(f"Blocked resources: {block_resources}")
            except Exception as e:
                logger.warning(f"Failed to block resources: {e}")
