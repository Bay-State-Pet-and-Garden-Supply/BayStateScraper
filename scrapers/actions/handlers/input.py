from __future__ import annotations

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("input_text")
class InputTextAction(BaseAction):
    """Action to input text into a form field."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        text = params.get("text")
        clear_first = params.get("clear_first", True)

        if not selector or text is None:
            raise WorkflowExecutionError("Input_text requires 'selector' and 'text' parameters")

        element = await self.ctx.find_element_safe(selector)

        if not element:
            raise WorkflowExecutionError(f"Input element not found: {selector}")

        try:
            if clear_first:
                await element.fill(str(text))
            else:
                await element.type(str(text))

            logger.debug(f"Input text into {selector}: {text}")
        except Exception as e:
            raise WorkflowExecutionError(f"Failed to input text into {selector}: {e}")
