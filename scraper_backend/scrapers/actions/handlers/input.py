from __future__ import annotations

import logging
from typing import Any

from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("input_text")
class InputTextAction(BaseAction):
    """Action to input text into a form field."""

    def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        text = params.get("text")
        clear_first = params.get("clear_first", True)

        if not selector or text is None:
            raise WorkflowExecutionError("Input_text requires 'selector' and 'text' parameters")

        element = self.executor.find_element_safe(selector)

        if not element:
            raise WorkflowExecutionError(f"Input element not found: {selector}")

        try:
            # Check for Playwright
            if hasattr(self.executor.browser, "page"):
                # Playwright
                if clear_first:
                    element.fill(str(text))
                else:
                    # If we don't clear, we might want to type sequentially
                    element.type(str(text))
            else:
                # Selenium
                if clear_first:
                    element.clear()
                element.send_keys(str(text))

            logger.debug(f"Input text into {selector}: {text}")
        except Exception as e:
            raise WorkflowExecutionError(f"Failed to input text into {selector}: {e}")
