from __future__ import annotations
import asyncio

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("parse_table")
class ParseTableAction(BaseAction):
    """Action to parse an HTML table into a dictionary or list."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        target_field = params.get("target_field")
        key_column = params.get("key_column", 0)
        value_column = params.get("value_column", 1)

        if not selector or not target_field:
            raise WorkflowExecutionError("Parse_table requires 'selector' and 'target_field'")

        try:
            table = self.ctx.find_element_safe(selector)
            if not table:
                logger.warning(f"Table not found: {selector}")
                self.ctx.results[target_field] = {}
                return

            rows = self.ctx.find_elements_safe(f"{selector} tr")

            result_data = {}

            for row in rows:
                # Use Playwright API if available
                if hasattr(row, "query_selector_all"):
                    cells = row.query_selector_all("td")
                    if not cells:
                        cells = row.query_selector_all("th")

                    if len(cells) >= max(key_column, value_column) + 1:
                        key = cells[key_column].inner_text().strip().rstrip(":")
                        value = cells[value_column].inner_text().strip()
                        if key:
                            result_data[key] = value
                else:
                    # Fallback for other element types
                    pass

            self.ctx.results[target_field] = result_data
            logger.debug(f"Parsed table into {target_field}: {len(result_data)} entries")

        except Exception as e:
            logger.warning(f"Failed to parse table: {e}")
            self.ctx.results[target_field] = {}
