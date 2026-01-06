from __future__ import annotations

import logging
import re
import time
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("click")
class ClickAction(BaseAction):
    """Action to click on an element with proper wait and retry logic."""

    def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        filter_text = params.get("filter_text")
        filter_text_exclude = params.get("filter_text_exclude")
        index = params.get("index", 0)

        if not selector:
            raise WorkflowExecutionError("Click action requires 'selector' parameter")

        max_retries = params.get("max_retries", 3 if self.executor.is_ci else 1)

        logger.debug(f"Attempting to click element: {selector} (max_retries: {max_retries})")

        # 1. Wait for presence using the shared wait action logic
        # We manually invoke the WaitForAction logic or rely on find_elements_safe implicitly if we want
        # But to match previous behavior, we should wait.
        try:
            # Re-use WaitForAction logic by instantiating it? Or just call wait_for_selector directly?
            # Easiest is to check if elements exist with a small loop/retry or just trust find_elements_safe with implicit wait
            # Since we abstracted, we rely on the backend.
            pass
        except Exception:
            pass

        # Now find elements and perform filtering and click
        try:
            elements = self.executor.find_elements_safe(selector)

            if not elements:
                # Retrying a few times if empty (implicit wait simulation)
                for _ in range(2):
                    time.sleep(1)
                    elements = self.executor.find_elements_safe(selector)
                    if elements:
                        break

            if not elements:
                raise WorkflowExecutionError(f"No elements found for selector: {selector}")

            filtered_elements = elements

            # Filtering logic (Text extraction abstraction required)
            if filter_text or filter_text_exclude:
                new_filtered = []
                for el in elements:
                    # Abstract text extraction
                    txt = self.executor._extract_value_from_element(el, "text") or ""

                    include_match = True
                    if filter_text:
                        if not re.search(filter_text, txt, re.IGNORECASE):
                            include_match = False

                    exclude_match = False
                    if filter_text_exclude:
                        if re.search(filter_text_exclude, txt, re.IGNORECASE):
                            exclude_match = True

                    if include_match and not exclude_match:
                        new_filtered.append(el)
                filtered_elements = new_filtered

            if not filtered_elements:
                raise WorkflowExecutionError(
                    f"No elements remaining after filtering for selector: {selector}"
                )

            if index >= len(filtered_elements):
                raise WorkflowExecutionError(
                    f"Index {index} out of bounds for filtered elements (count: {len(filtered_elements)}) for selector: {selector}"
                )

            element_to_click = filtered_elements[index]

            # Click Logic (Backend Specific)
            is_playwright = hasattr(self.executor.browser, "page")

            if is_playwright:
                try:
                    element_to_click.scroll_into_view_if_needed()
                    element_to_click.click()
                    logger.info(f"Successfully clicked element (Playwright): {selector}")
                except Exception as pw_e:
                    logger.warning(f"Playwright click failed: {pw_e}. Attempting force click.")
                    try:
                        element_to_click.click(force=True)
                    except Exception as force_e:
                        raise WorkflowExecutionError(
                            f"Failed to click element (Playwright force): {force_e}"
                        )
            else:
                # Selenium Logic
                try:
                    self.executor.browser.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                        element_to_click,
                    )
                    time.sleep(0.5)  # Brief pause after scrolling
                except Exception as scroll_e:
                    logger.debug(f"Could not scroll element into view: {scroll_e}")

                # Attempt click with JS fallback
                try:
                    element_to_click.click()
                    logger.info(f"Successfully clicked element: {selector} at index {index}")
                except Exception as click_error:
                    logger.warning(
                        f"Standard click failed for {selector}: {click_error}. Attempting JS click."
                    )
                    try:
                        self.executor.browser.driver.execute_script(
                            "arguments[0].click();", element_to_click
                        )
                        logger.info(
                            f"Successfully clicked element via JS: {selector} at index {index}"
                        )
                    except Exception as js_error:
                        raise WorkflowExecutionError(
                            f"Failed to click element (standard and JS): {js_error}"
                        )

            # Optional wait after click
            wait_time = params.get("wait_after", 0)
            if wait_time > 0:
                logger.debug(f"Waiting {wait_time}s after click")
                time.sleep(wait_time)

        except Exception as e:
            raise WorkflowExecutionError(f"Failed to click element after waiting: {e}")
