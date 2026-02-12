"""
Normalization engine for applying transformation rules to scraped results.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from scrapers.models.config import NormalizationRule

logger = logging.getLogger(__name__)


class NormalizationEngine:
    """Engine for normalizing extracted scraping results."""

    def normalize_results(
        self,
        results: dict[str, Any],
        normalization_rules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply normalization rules to results.

        Args:
            results: Dictionary of extracted results to normalize
            normalization_rules: List of normalization rule dictionaries.
                Each rule should have:
                - field: str - Name of the field to normalize
                - action: str - Normalization action to apply
                - params: dict - Optional parameters for the action

        Supported actions:
        - title_case: Convert to title case
        - lowercase: Convert to lowercase
        - uppercase: Convert to uppercase
        - trim/strip: Remove leading/trailing whitespace
        - remove_prefix: Remove a prefix string (requires 'prefix' param)
        - extract_weight: Extract weight value and convert to lbs

        Returns:
            dict: The normalized results dictionary (modified in place)
        """
        if not normalization_rules:
            return results

        for rule in normalization_rules:
            field = rule.get("field")
            action = rule.get("action")
            params = rule.get("params", {})

            if not field or not action:
                logger.warning(f"Skipping invalid normalization rule: {rule}")
                continue

            if field in results:
                value = results[field]
                if isinstance(value, str):
                    try:
                        normalized_value = self._apply_normalization(value, action, params)
                        results[field] = normalized_value
                        logger.debug(f"Normalized field '{field}': '{value}' -> '{normalized_value}'")
                    except Exception as e:
                        logger.warning(f"Failed to normalize field '{field}' with action '{action}': {e}")

        return results

    def _apply_normalization(self, value: str, action: str, params: dict[str, Any]) -> str:
        """Apply a single normalization action to a value.

        Args:
            value: The string value to normalize
            action: The normalization action to apply
            params: Parameters for the action

        Returns:
            str: The normalized value
        """
        if action == "title_case":
            return value.title()
        elif action == "lowercase":
            return value.lower()
        elif action == "uppercase":
            return value.upper()
        elif action in ("trim", "strip"):
            return value.strip()
        elif action == "remove_prefix":
            prefix = params.get("prefix", "")
            if prefix and value.startswith(prefix):
                return value[len(prefix) :].strip()
            return value
        elif action == "remove_suffix":
            suffix = params.get("suffix", "")
            if suffix and value.endswith(suffix):
                return value[: -len(suffix)].strip()
            return value
        elif action == "replace":
            old = params.get("old", "")
            new = params.get("new", "")
            return value.replace(old, new)
        elif action == "regex_replace":
            pattern = params.get("pattern", "")
            replacement = params.get("replacement", "")
            if pattern:
                return re.sub(pattern, replacement, value)
            return value
        elif action == "regex_extract":
            pattern = params.get("pattern", "")
            group = params.get("group", 0)
            if pattern:
                match = re.search(pattern, value)
                if match:
                    return match.group(group)
            return value
        elif action == "extract_weight":
            return self._extract_weight(value)
        else:
            logger.warning(f"Unknown normalization action: {action}")
            return value

    def _extract_weight(self, value: str) -> str:
        """Extract number and unit from weight string, convert to lbs.

        Handles: "5 lbs", "5.5kg", "Weight: 10 oz", etc.

        Args:
            value: The weight string to parse

        Returns:
            str: Weight in lbs formatted to 2 decimal places
        """
        # Match number (int or float) followed by optional unit
        match = re.search(r"(\d+(?:\.\d+)?)\s*(lbs?|lb|oz|kg|g)?", value, re.IGNORECASE)
        if match:
            weight = float(match.group(1))
            unit = (match.group(2) or "lb").lower()

            if unit in ["oz"]:
                weight = weight / 16.0
            elif unit in ["kg"]:
                weight = weight * 2.20462
            elif unit in ["g"]:
                weight = weight * 0.00220462

            # Format to 2 decimal places
            return f"{weight:.2f}"

        return value

    def normalize_with_model(
        self,
        results: dict[str, Any],
        rules: list[NormalizationRule] | None = None,
    ) -> dict[str, Any]:
        """Apply normalization rules using NormalizationRule model instances.

        Args:
            results: Dictionary of extracted results to normalize
            rules: List of NormalizationRule objects

        Returns:
            dict: The normalized results dictionary
        """
        if not rules:
            return results

        # Convert NormalizationRule objects to dict format
        rule_dicts = []
        for rule in rules:
            rule_dicts.append(
                {
                    "field": rule.field,
                    "action": rule.action,
                    "params": rule.params,
                }
            )

        return self.normalize_results(results, rule_dicts)
