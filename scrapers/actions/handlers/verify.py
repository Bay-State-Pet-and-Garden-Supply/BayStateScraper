from __future__ import annotations

import logging
import re
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("verify_value")
class VerifyValueAction(BaseAction):
    """Action to verify that a value matches an expected pattern or value."""

    def execute(self, params: dict[str, Any]) -> None:
        field = params.get("field")
        expected = params.get("expected")
        match_mode = params.get("match_mode", "exact")  # exact, contains, regex

        if not field:
            raise WorkflowExecutionError("Verify_value requires 'field' parameter")

        actual_value = self.executor.results.get(field)
        if actual_value is None:
            logger.warning(f"Field {field} is missing, verification failed")
            # We might want to fail the workflow or just log a warning depending on config
            # For now, let's assume we want to fail if verification is strict
            if params.get("strict", True):
                raise WorkflowExecutionError(f"Verification failed: Field {field} is missing")
            return

        actual_str = str(actual_value)

        # If expected is not provided, we might be verifying against a context value (like searched SKU)
        # But for now let's assume expected is passed explicitly or we check for non-empty
        if expected is None:
            if not actual_str:
                if params.get("strict", True):
                    raise WorkflowExecutionError(f"Verification failed: Field {field} is empty")
            return

        matched = False
        if match_mode == "exact":
            matched = actual_str == str(expected)
        elif match_mode == "contains":
            matched = str(expected) in actual_str
        elif match_mode == "regex":
            matched = bool(re.search(str(expected), actual_str))

        if not matched:
            msg = f"Verification failed for {field}: expected '{expected}' ({match_mode}), got '{actual_str}'"
            logger.warning(msg)
            if params.get("strict", True):
                raise WorkflowExecutionError(msg)
        else:
            logger.debug(f"Verification passed for {field}")


@ActionRegistry.register("filter_brand")
class FilterBrandAction(BaseAction):
    """Action to filter brand name from product name."""

    def execute(self, params: dict[str, Any]) -> None:
        name_field = params.get("name_field", "product_name")
        brand_field = params.get("brand_field", "brand")

        name = self.executor.results.get(name_field)
        brand = self.executor.results.get(brand_field)

        if not name or not brand:
            return

        # Simple case-insensitive removal
        brand_pattern = re.escape(str(brand))

        # Remove "Brand: " prefix if present in name
        pattern = rf"^{brand_pattern}\s*[:|-]?\s*"
        new_name = re.sub(pattern, "", str(name), flags=re.IGNORECASE).strip()

        # Remove from end
        if new_name.lower().endswith(str(brand).lower()):
            new_name = new_name[: -(len(brand))].strip().rstrip(":-")

        if len(new_name) < 3:  # Don't make it too short
            new_name = name

        self.executor.results[name_field] = new_name
        logger.debug(f"Filtered brand '{brand}' from name: '{name}' -> '{new_name}'")
