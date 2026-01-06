from __future__ import annotations

import logging
import time
from typing import Any

# Selenium imports removed - migrated to Playwright
# from selenium.common.exceptions import TimeoutException
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.webdriver.support.ui import WebDriverWait
from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.exceptions import TimeoutError, WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("wait_for")
class WaitForAction(BaseAction):
    """Action to wait for an element to be present."""

    def execute(self, params: dict[str, Any]) -> None:
        selector_param = params.get("selector")
        timeout = params.get("timeout", self.executor.timeout)

        if not selector_param:
            raise WorkflowExecutionError("Wait_for action requires 'selector' parameter")

        selectors = selector_param if isinstance(selector_param, list) else [selector_param]

        logger.debug(
            f"Waiting for any of elements: {selectors} (timeout: {timeout}s, CI: {self.executor.is_ci})"
        )

        start_time = time.time()

        try:
            # Check for Playwright
            if hasattr(self.executor.browser, "page"):
                # Playwright logic
                # For 'any of', we might need to iterate or use a combined selector if CSS
                # Playwright doesn't natively have "wait for any of these separate selectors" easily in one call
                # except via Promise.race, but here we are in sync (mostly) or adapting

                # Simple strategy: Loop with short timeout until overall timeout
                end_time = start_time + timeout
                found = False

                while time.time() < end_time:
                    for selector in selectors:
                        try:
                            # Normalize XPath for Playwright if needed
                            target = selector
                            if (
                                target.startswith("//") or target.startswith(".//")
                            ) and not target.startswith("xpath="):
                                target = f"xpath={target}"

                            # Use a short timeout for the individual check (e.g. 100ms)
                            # but verify state='attached' or 'visible'
                            self.executor.browser.page.wait_for_selector(
                                target, state="attached", timeout=100
                            )
                            found = True
                            break
                        except Exception:
                            continue

                    if found:
                        break

                    # Small sleep to prevent CPU spin if selectors fail instantly
                    time.sleep(0.5)

                if not found:
                    raise TimeoutError("Playwright wait timed out")

            else:
                # Selenium logic removed - raise error if not Playwright
                raise TimeoutError(
                    "Selenium backend is no longer supported for wait_for action. Use Playwright."
                )

            wait_duration = time.time() - start_time

            # Performance warning for slow selectors (efficiency check)
            if wait_duration > (timeout * 0.5) and wait_duration > 2.0:
                logger.warning(
                    f"Slow selector detected: Found after {wait_duration:.2f}s "
                    f"(>50% of {timeout}s timeout). Consider optimizing: {selectors}"
                )
            else:
                logger.info(f"Element found after {wait_duration:.2f}s from selectors: {selectors}")

        except (TimeoutError, Exception) as e:
            wait_duration = time.time() - start_time
            logger.warning(
                f"TIMEOUT: Element not found within {timeout}s (waited {wait_duration:.2f}s): {selectors} - {e}"
            )

            # Log debugging info
            try:
                # Use executor's browser.current_url abstraction if possible, or direct access
                current_url = getattr(self.executor.browser, "current_url", "unknown")
                if not current_url and hasattr(self.executor.browser, "driver"):
                    current_url = self.executor.browser.driver.current_url

                logger.debug(f"Current page URL: {current_url}")
            except Exception:
                pass

            # Raise specific TimeoutError to ensure proper failure handling
            raise TimeoutError(
                f"Element wait timed out after {timeout}s: {selectors}",
                context=None,  # Context will be added by executor
            )
