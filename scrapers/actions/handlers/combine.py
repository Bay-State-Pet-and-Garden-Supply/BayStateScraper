from __future__ import annotations
import asyncio

import logging
import re
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("combine_fields")
class CombineFieldsAction(BaseAction):
    """Action to combine multiple extracted fields into a single field."""

    async def execute(self, params: dict[str, Any]) -> None:
        target_field = params.get("target_field")
        format_string = params.get("format")
        fields = params.get("fields", [])

        if not target_field or not format_string:
            raise WorkflowExecutionError(
                "Combine_fields requires 'target_field' and 'format' parameters"
            )

        # Collect values for all required fields
        field_values = {}
        for field in fields:
            value = self.ctx.results.get(field)
            if value is None:
                value = ""
            field_values[field] = str(value).strip()

        try:
            # Format the string
            combined_value = format_string.format(**field_values)

            # Optional cleaning
            cleaners = params.get("cleaners", [])
            for cleaner in cleaners:
                if cleaner.get("type") == "replace":
                    pattern = cleaner.get("pattern")
                    replacement = cleaner.get("replacement", "")
                    if pattern:
                        combined_value = re.sub(pattern, replacement, combined_value).strip()
                elif cleaner.get("type") == "strip":
                    chars = cleaner.get("chars")
                    combined_value = combined_value.strip(chars)

            self.ctx.results[target_field] = combined_value
            logger.debug(f"Combined fields into {target_field}: {combined_value}")

        except KeyError as e:
            logger.warning(f"Missing field for combination: {e}")
            self.ctx.results[target_field] = None
        except Exception as e:
            logger.error(f"Error combining fields: {e}")
            self.ctx.results[target_field] = None
