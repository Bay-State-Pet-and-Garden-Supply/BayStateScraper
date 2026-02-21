"""
Combined extract and transform action for efficient single-pass field extraction.

This action combines the functionality of 'extract' and 'transform_value' into a single
step, reducing config complexity and eliminating step dispatch overhead.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)

DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS = 1500


def _coerce_timeout_ms(value: Any, default: int) -> int:
    if value is None:
        return default

    try:
        timeout_ms = int(value)
    except (TypeError, ValueError):
        return default

    return max(0, timeout_ms)


@ActionRegistry.register("extract_and_transform")
class ExtractAndTransformAction(BaseAction):
    """
    Single-pass extraction with inline transformations.

    This action extracts data from the page and applies transformations in one step,
    providing a cleaner YAML syntax and slightly better performance than separate
    extract + transform_value steps.

    YAML Usage:
    ```yaml
    - action: extract_and_transform
      params:
        fields:
          - name: Name
            selector: "#productTitle"
          - name: Brand
            selector: "#bylineInfo"
            transform:
              - type: regex_extract
                pattern: "Visit the (.+) Store"
          - name: Images
            selector: "#altImages img"
            attribute: src
            multiple: true
            transform:
              - type: replace
                pattern: "_AC_US40_"
                replacement: "_AC_SL1500_"
          - name: Price
            selector: ".a-price-whole"
            required: false
    ```

    Field Configuration:
        - name (required): Result field name
        - selector (required): CSS selector or XPath
        - attribute (optional): Element attribute to extract (default: text)
        - multiple (optional): Extract all matching elements as list (default: false)
        - required (optional): Fail if element not found (default: true)
        - transform (optional): List of transformations to apply

    Transform Types:
        - replace: { type: replace, pattern: "...", replacement: "..." }
        - strip: { type: strip, chars: "..." }
        - lower/upper/title: { type: lower }
        - regex_extract: { type: regex_extract, pattern: "...", group: 1 }
    """

    async def execute(self, params: dict[str, Any]) -> None:
        fields = params.get("fields", [])

        if not fields:
            raise WorkflowExecutionError("extract_and_transform requires 'fields' parameter with list of field configs")

        logger.debug(f"Starting extract_and_transform for {len(fields)} fields")

        default_timeout_ms = _coerce_timeout_ms(
            params.get("field_timeout_ms", DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS),
            DEFAULT_OPTIONAL_FIELD_TIMEOUT_MS,
        )

        for field_config in fields:
            await self._process_field(field_config, default_timeout_ms)

        logger.info(f"extract_and_transform completed. Extracted: {list(self.ctx.results.keys())}")

    async def _process_field(self, field_config: dict[str, Any], default_timeout_ms: int) -> None:
        """Process a single field: extract from DOM and apply transforms."""
        name = field_config.get("name")
        selector = field_config.get("selector")
        attribute = field_config.get("attribute", "text")
        multiple = field_config.get("multiple", False)
        required = field_config.get("required", True)
        transforms = field_config.get("transform", [])
        timeout_ms_value = field_config.get("timeout_ms")

        if not name:
            raise WorkflowExecutionError("Field config missing 'name'")

        if not selector:
            raise WorkflowExecutionError(f"Field '{name}' missing 'selector'")

        try:
            if timeout_ms_value is None:
                timeout_ms = None if required else default_timeout_ms
            else:
                timeout_ms = _coerce_timeout_ms(timeout_ms_value, default_timeout_ms)
            if multiple:
                value = await self._extract_multiple(selector, attribute, timeout_ms)
            else:
                value = await self._extract_single(selector, attribute, required, timeout_ms)

            # Check required constraint
            if required and value is None:
                logger.warning(f"Required field '{name}' not found (selector: {selector})")
                self.ctx.results[name] = [] if multiple else None
                return

            if value is None:
                self.ctx.results[name] = [] if multiple else None
                return

            # Apply transformations
            if transforms:
                if isinstance(value, list):
                    value = [self._apply_transformations(v, transforms) for v in value if v]
                else:
                    value = self._apply_transformations(value, transforms)

            self.ctx.results[name] = value
            logger.debug(f"Extracted '{name}': {value[:100] if isinstance(value, str) else value}")

        except Exception as e:
            logger.warning(f"Error extracting field '{name}': {e}")
            self.ctx.results[name] = [] if multiple else None

    async def _extract_single(
        self,
        selector: str,
        attribute: str,
        required: bool,
        timeout_ms: int | None,
    ) -> str | None:
        """Extract a single value from the first matching element."""
        element = await self.ctx.find_element_safe(
            selector,
            required=required,
            timeout=timeout_ms,
        )
        if not element:
            return None
        return await self.ctx.extract_value_from_element(element, attribute)

    async def _extract_multiple(
        self,
        selector: str,
        attribute: str,
        timeout_ms: int | None,
    ) -> list[str]:
        """Extract values from all matching elements, deduplicated."""
        elements = await self.ctx.find_elements_safe(selector, timeout=timeout_ms)
        values = []
        seen = set()

        for element in elements:
            value = await self.ctx.extract_value_from_element(element, attribute)
            if value and value not in seen:
                seen.add(value)
                values.append(value)

        return values

    def _apply_transformations(self, value: str, transformations: list[dict[str, Any]]) -> str:
        """Apply a sequence of transformations to a value."""
        result = str(value) if value else ""

        for transform in transformations:
            t_type = transform.get("type")

            if t_type == "replace":
                pattern = transform.get("pattern")
                replacement = transform.get("replacement", "")
                if pattern:
                    try:
                        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE).strip()
                    except re.error as e:
                        logger.warning(f"Invalid regex pattern '{pattern}': {e}")

            elif t_type == "strip":
                chars = transform.get("chars")
                result = result.strip(chars) if chars else result.strip()

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
                    try:
                        match = re.search(pattern, result, flags=re.IGNORECASE)
                        if match:
                            result = match.group(group)
                    except (re.error, IndexError) as e:
                        logger.warning(f"Regex extraction failed for pattern '{pattern}': {e}")

            elif t_type == "prefix":
                prefix = transform.get("value", "")
                result = f"{prefix}{result}"

            elif t_type == "suffix":
                suffix = transform.get("value", "")
                result = f"{result}{suffix}"

            elif t_type == "default":
                # Use default value if current result is empty
                if not result or result.strip() == "":
                    result = transform.get("value", "")

            else:
                logger.warning(f"Unknown transform type: {t_type}")

        return result
