from __future__ import annotations

import logging
import re
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("parse_weight")
class ParseWeightAction(BaseAction):
    """Action to parse and normalize weight strings."""

    def execute(self, params: dict[str, Any]) -> None:
        field = params.get("field")
        target_unit = params.get("target_unit", "lb")  # lb, kg, oz, g

        if not field:
            raise WorkflowExecutionError("Parse_weight requires 'field' parameter")

        raw_weight = self.executor.results.get(field)
        if not raw_weight:
            logger.warning(f"No weight found in field {field}")
            return

        # Extract number and unit
        # Matches: 10.5 lbs, 10kg, 10 oz, etc.
        match = re.search(r"([\d\.]+)\s*([a-zA-Z]+)", str(raw_weight))
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()

            # Normalize unit
            if unit in ["lbs", "lb", "pound", "pounds"]:
                normalized_unit = "lb"
            elif unit in ["kg", "kgs", "kilogram", "kilograms"]:
                normalized_unit = "kg"
            elif unit in ["oz", "ounce", "ounces"]:
                normalized_unit = "oz"
            elif unit in ["g", "gram", "grams"]:
                normalized_unit = "g"
            else:
                logger.warning(f"Unknown weight unit: {unit}")
                self.executor.results[field] = raw_weight
                return

            # Convert to target unit
            converted_value = value
            if normalized_unit != target_unit:
                # Convert to grams first
                grams = 0.0
                if normalized_unit == "lb":
                    grams = value * 453.592
                elif normalized_unit == "kg":
                    grams = value * 1000
                elif normalized_unit == "oz":
                    grams = value * 28.3495
                elif normalized_unit == "g":
                    grams = value

                # Convert from grams to target
                if target_unit == "lb":
                    converted_value = grams / 453.592
                elif target_unit == "kg":
                    converted_value = grams / 1000
                elif target_unit == "oz":
                    converted_value = grams / 28.3495
                elif target_unit == "g":
                    converted_value = grams

            self.executor.results[field] = f"{converted_value:.2f} {target_unit}"
            logger.debug(f"Parsed weight: {raw_weight} -> {self.executor.results[field]}")
        else:
            logger.warning(f"Could not parse weight string: {raw_weight}")
