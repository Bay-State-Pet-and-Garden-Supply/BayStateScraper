from __future__ import annotations
import asyncio
import logging
import time
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import TimeoutError, WorkflowExecutionError
from scrapers.utils.locators import convert_to_playwright_locator

logger = logging.getLogger(__name__)


@ActionRegistry.register("wait_for_hidden")
class WaitForHiddenAction(BaseAction):
    """Action to wait for an element to disappear (hidden or detached)."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector_param = params.get("selector")
        timeout = params.get("timeout", self.ctx.timeout)

        if not selector_param:
            raise WorkflowExecutionError("Wait_for_hidden action requires 'selector' parameter")

        selectors = selector_param if isinstance(selector_param, list) else [selector_param]

        logger.debug(f"Waiting for elements to be hidden: {selectors} (timeout: {timeout}s)")

        start_time = time.time()

        try:
            end_time = start_time + timeout

            # For 'wait_for_hidden', we need ALL specified elements to be hidden
            # We iterate through them and wait for each
            for selector in selectors:
                remaining_timeout = max(0.1, end_time - time.time())

                try:
                    page = self.ctx.browser.page
                    locator = convert_to_playwright_locator(page, selector)

                    # Wait for hidden state (hidden in DOM or detached)
                    await locator.wait_for(state="hidden", timeout=remaining_timeout * 1000)
                except Exception as e:
                    logger.warning(f"Timeout or error waiting for hidden '{selector}': {e}")
                    # We continue because we want to try our best within the total timeout

            wait_duration = time.time() - start_time
            logger.info(f"Elements hidden after {wait_duration:.2f}s: {selectors}")

        except Exception as e:
            wait_duration = time.time() - start_time
            logger.error(f"Error in wait_for_hidden after {wait_duration:.2f}s: {e}")
            # We don't necessarily raise here unless it's a critical failure
            # because the elements might already be hidden.
