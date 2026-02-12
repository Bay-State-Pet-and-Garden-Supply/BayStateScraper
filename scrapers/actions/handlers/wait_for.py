from __future__ import annotations
import asyncio

import logging
import time
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import TimeoutError, WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("wait_for")
class WaitForAction(BaseAction):
    """Action to wait for an element to be present."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector_param = params.get("selector")
        timeout = params.get("timeout", self.ctx.timeout)

        if not selector_param:
            raise WorkflowExecutionError("Wait_for action requires 'selector' parameter")

        selectors = selector_param if isinstance(selector_param, list) else [selector_param]

        logger.debug(f"Waiting for any of elements: {selectors} (timeout: {timeout}s, CI: {self.ctx.is_ci})")

        start_time = time.time()

        try:
            end_time = start_time + timeout
            found = False

            while time.time() < end_time:
                for selector in selectors:
                    try:
                        target = selector
                        if (target.startswith("//") or target.startswith(".//")) and not target.startswith("xpath="):
                            target = f"xpath={target}"

                        self.ctx.browser.page.wait_for_selector(target, state="attached", timeout=100)
                        found = True
                        break
                    except Exception:
                        continue

                if found:
                    break

                await asyncio.sleep(0.5)

            if not found:
                raise TimeoutError("Playwright wait timed out")

            wait_duration = time.time() - start_time

            # Performance warning for slow selectors (efficiency check)
            if wait_duration > (timeout * 0.5) and wait_duration > 2.0:
                logger.warning(f"Slow selector detected: Found after {wait_duration:.2f}s (>50% of {timeout}s timeout). Consider optimizing: {selectors}")
            else:
                logger.info(f"Element found after {wait_duration:.2f}s from selectors: {selectors}")

        except (TimeoutError, Exception) as e:
            wait_duration = time.time() - start_time
            logger.warning(f"TIMEOUT: Element not found within {timeout}s (waited {wait_duration:.2f}s): {selectors} - {e}")

            # Log debugging info
            try:
                current_url = self.ctx.browser.page.url
                logger.debug(f"Current page URL: {current_url}")
            except Exception:
                pass

            # Raise specific TimeoutError to ensure proper failure handling
            raise TimeoutError(
                f"Element wait timed out after {timeout}s: {selectors}",
                context=None,  # Context will be added by executor
            )
