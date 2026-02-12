from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("click")
class ClickAction(BaseAction):
    """Action to click on an element with proper wait and retry logic."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        filter_text = params.get("filter_text")
        filter_text_exclude = params.get("filter_text_exclude")
        index = params.get("index", 0)

        if not selector:
            raise WorkflowExecutionError("Click action requires 'selector' parameter")

        max_retries = params.get("max_retries", 3 if self.ctx.is_ci else 1)

        logger.debug(f"Attempting to click element: {selector} (max_retries: {max_retries})")

        # Find elements and perform filtering and click
        try:
            elements = await self.ctx.find_elements_safe(selector)

            if not elements:
                # Retrying a few times if empty (implicit wait simulation)
                for _ in range(2):
                    await asyncio.sleep(1)
                    elements = await self.ctx.find_elements_safe(selector)
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
                    txt = await self.ctx._extract_value_from_element(el, "text") or ""

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
                raise WorkflowExecutionError(f"No elements remaining after filtering for selector: {selector}")

            if index >= len(filtered_elements):
                raise WorkflowExecutionError(f"Index {index} out of bounds for filtered elements (count: {len(filtered_elements)}) for selector: {selector}")

            element_to_click = filtered_elements[index]

            try:
                await element_to_click.scroll_into_view_if_needed()
                await element_to_click.click()
                logger.info(f"Clicked element: {selector} (index {index})")
            except Exception as click_err:
                logger.warning(f"Click failed: {click_err}. Attempting force click.")
                try:
                    await element_to_click.click(force=True)
                    logger.info(f"Force clicked element: {selector}")
                except Exception as force_err:
                    logger.warning(f"Force click failed: {force_err}. Attempting dispatch_event click.")
                    try:
                        await element_to_click.dispatch_event("click")
                        logger.info(f"Successfully clicked element via dispatch_event: {selector} at index {index}")
                    except Exception as dispatch_err:
                        raise WorkflowExecutionError(
                            f"Failed to click element '{selector}' (standard, force, and dispatch_event): {dispatch_err}"
                        ) from dispatch_err

            # Optional wait after click
            wait_time = params.get("wait_after", 0)
            if wait_time > 0:
                logger.debug(f"Waiting {wait_time}s after click")
                await asyncio.sleep(wait_time)

        except Exception as e:
            raise WorkflowExecutionError(f"Failed to click element after waiting: {e}")
