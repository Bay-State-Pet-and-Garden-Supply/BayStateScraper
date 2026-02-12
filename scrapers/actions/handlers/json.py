from __future__ import annotations
import asyncio

import json
import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("extract_from_json")
class ExtractFromJsonAction(BaseAction):
    """Action to extract data from a JSON string (e.g., in a script tag)."""

    async def execute(self, params: dict[str, Any]) -> None:
        source_field = params.get("source_field")
        json_path = params.get("json_path")
        target_field = params.get("target_field")

        if not source_field or not json_path or not target_field:
            raise WorkflowExecutionError(
                "Extract_from_json requires 'source_field', 'json_path', and 'target_field'"
            )

        json_content = self.ctx.results.get(source_field)
        if not json_content:
            logger.warning(f"Source field {source_field} is empty")
            self.ctx.results[target_field] = None
            return

        try:
            if isinstance(json_content, str):
                data = json.loads(json_content)
            else:
                data = json_content

            # Simple JSON path traversal (dot notation)
            current = data
            for key in json_path.split("."):
                if isinstance(current, dict):
                    current = current.get(key)
                elif isinstance(current, list) and key.isdigit():
                    current = current[int(key)]
                else:
                    current = None
                    break

            self.ctx.results[target_field] = current
            logger.debug(f"Extracted JSON path {json_path} to {target_field}: {current}")

        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from {source_field}")
            self.ctx.results[target_field] = None
        except Exception as e:
            logger.error(f"Error extracting from JSON: {e}")
            self.ctx.results[target_field] = None
