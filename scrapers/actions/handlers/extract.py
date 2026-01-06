from __future__ import annotations

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("extract_single")
class ExtractSingleAction(BaseAction):
    """Action to extract a single value using a selector."""

    def execute(self, params: dict[str, Any]) -> None:
        field_name = params.get("field")

        # Support ID-based lookup (selector_id) with fallback to name-based (selector)
        selector_id = params.get("selector_id")
        selector_name = params.get("selector")

        identifier = selector_id or selector_name

        if not field_name or not identifier:
            raise WorkflowExecutionError(
                "Extract_single requires 'field' and 'selector_id' (or 'selector') parameters"
            )

        selector_config = self.executor.resolve_selector(identifier)
        if not selector_config:
            raise WorkflowExecutionError(f"Selector '{identifier}' not found in config")

        element = self.executor.find_element_safe(selector_config.selector)

        if element:
            value = self.executor._extract_value_from_element(element, selector_config.attribute)
            self.executor.results[field_name] = value
            logger.debug(f"Extracted {field_name}: {value}")
        else:
            logger.warning(f"Element not found for field: {field_name}")
            self.executor.results[field_name] = None


@ActionRegistry.register("extract_multiple")
class ExtractMultipleAction(BaseAction):
    """Action to extract multiple values using a selector."""

    def execute(self, params: dict[str, Any]) -> None:
        field_name = params.get("field")

        # Support ID-based lookup (selector_id) with fallback to name-based (selector)
        selector_id = params.get("selector_id")
        selector_name = params.get("selector")

        identifier = selector_id or selector_name

        if not field_name or not identifier:
            raise WorkflowExecutionError(
                "Extract_multiple requires 'field' and 'selector_id' (or 'selector') parameters"
            )

        selector_config = self.executor.resolve_selector(identifier)
        if not selector_config:
            raise WorkflowExecutionError(f"Selector '{identifier}' not found in config")

        try:
            elements = self.executor.find_elements_safe(selector_config.selector)
            values = []
            for element in elements:
                value = self.executor._extract_value_from_element(
                    element, selector_config.attribute
                )
                if value:
                    values.append(value)
            self.executor.results[field_name] = values
            logger.debug(f"Extracted {len(values)} items for {field_name}")
        except Exception as e:
            logger.warning(f"Failed to extract multiple values for {field_name}: {e}")
            self.executor.results[field_name] = []


@ActionRegistry.register("extract")
class ExtractAction(BaseAction):
    """Action to extract multiple fields at once (legacy compatibility)."""

    def execute(self, params: dict[str, Any]) -> None:
        # Support ID-based lookup (selector_ids) with fallback to name-based (fields)
        selector_ids = params.get("selector_ids", [])
        fields = params.get("fields", [])

        # Use selector_ids if available, otherwise fall back to fields
        identifiers = selector_ids if selector_ids else fields

        if not identifiers:
            logger.warning(
                "No selectors specified for extract action (need 'selector_ids' or 'fields')"
            )
            return

        logger.debug(f"Starting extract action for identifiers: {identifiers}")

        for identifier in identifiers:
            selector_config = self.executor.resolve_selector(identifier)
            if not selector_config:
                logger.warning(f"Selector '{identifier}' not found in config")
                continue

            # Use selector name as the result key (human-readable)
            result_key = selector_config.name

            try:
                if selector_config.multiple:
                    elements = self.executor.find_elements_safe(selector_config.selector)
                    values = []
                    for element in elements:
                        value = self.executor._extract_value_from_element(
                            element, selector_config.attribute
                        )
                        if value:
                            values.append(value)
                    # Deduplicate values while preserving order
                    seen = set()
                    deduplicated_values = []
                    for value in values:
                        if value not in seen:
                            seen.add(value)
                            deduplicated_values.append(value)
                    self.executor.results[result_key] = deduplicated_values
                else:
                    element = self.executor.find_element_safe(selector_config.selector)
                    value = None
                    if element:
                        value = self.executor._extract_value_from_element(
                            element, selector_config.attribute
                        )
                    self.executor.results[result_key] = value
                logger.debug(f"Extracted {result_key}: {self.executor.results[result_key]}")
            except Exception as e:
                logger.warning(f"Error extracting field {result_key}: {e}")
                self.executor.results[result_key] = [] if selector_config.multiple else None
        logger.info(f"Extract action completed. Results: {self.executor.results}")
