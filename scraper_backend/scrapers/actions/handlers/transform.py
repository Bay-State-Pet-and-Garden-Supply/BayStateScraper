import logging
import re
from typing import Any

from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("transform_value")
class TransformValueAction(BaseAction):
    """Action to transform/clean a value in the results.

    Can either transform in-place (using 'field') or extract to a new field
    (using 'source_field' + 'target_field').
    """

    def execute(self, params: dict[str, Any]) -> None:
        # Support both in-place transformation and source->target extraction
        source_field = params.get("source_field") or params.get("field")
        target_field = params.get("target_field") or params.get("field")
        transformations = params.get("transformations", [])

        # Support simple regex extraction with regex param
        regex = params.get("regex")
        if regex and not transformations:
            transformations = [{"type": "regex_extract", "pattern": regex, "group": 1}]

        if not source_field or not target_field:
            raise WorkflowExecutionError(
                "Transform_value requires 'field' or 'source_field' parameter"
            )

        value = self.executor.results.get(source_field)
        if value is None:
            logger.warning(f"Field {source_field} not found in results, skipping transformation")
            return

        # Handle list of values or single value
        if isinstance(value, list):
            self.executor.results[target_field] = [
                self._apply_transformations(v, transformations) for v in value
            ]
        else:
            self.executor.results[target_field] = self._apply_transformations(
                str(value), transformations
            )

        logger.debug(
            f"Transformed {source_field} -> {target_field}: {self.executor.results[target_field]}"
        )

    def _apply_transformations(self, value: str, transformations: list) -> str:
        result = value
        for transform in transformations:
            t_type = transform.get("type")

            if t_type == "replace":
                pattern = transform.get("pattern")
                replacement = transform.get("replacement", "")
                if pattern:
                    result = re.sub(pattern, replacement, result, flags=re.IGNORECASE).strip()

            elif t_type == "strip":
                chars = transform.get("chars")
                result = result.strip(chars)

            elif t_type == "lower":
                result = result.lower()

            elif t_type == "upper":
                result = result.upper()

            elif t_type == "title":
                result = result.title()

            elif t_type == "regex_extract":
                pattern = transform.get("pattern")
                group = transform.get("group", 1)
                if pattern:
                    match = re.search(pattern, result, flags=re.IGNORECASE)
                    if match:
                        try:
                            result = match.group(group)
                        except IndexError:
                            pass  # Keep original if group not found

        return result
