"""
AI validation action handler for validating extracted data from ai_extract.

This action validates AI-extracted data against requirements including:
- Required field presence
- SKU matching
- Confidence threshold
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("ai_validate")
class AIValidateAction(BaseAction):
    """
    Action to validate AI-extracted data against requirements.

    Validates data extracted by ai_extract action and produces a validation
    report with pass/fail status and detailed errors.

    Parameters:
        required_fields: List of field names that must be present and non-empty
        sku_must_match: Whether to validate that extracted SKU matches query SKU
        min_confidence: Minimum confidence score required (0.0 to 1.0)

    Context Dependencies:
        ctx.results["ai_extracted_data"]: The extracted data to validate
        ctx.results["sku"]: The query SKU (fallback to ctx.context["sku"])

    Results Set:
        ctx.results["validation_passed"]: Boolean pass/fail status
        ctx.results["validation_errors"]: List of error message strings
        ctx.results["validation_report"]: Full validation report dict
    """

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute AI validation against extracted data.

        Args:
            params: Dictionary containing:
                - required_fields: List[str] of required field names
                - sku_must_match: bool (default: True)
                - min_confidence: float (default: 0.0)

        Returns:
            Validation report dictionary with pass/fail status
        """
        required_fields = self._coerce_list(params.get("required_fields", []))
        sku_must_match = self._coerce_bool(params.get("sku_must_match", True))
        min_confidence = self._coerce_float(params.get("min_confidence", 0.0), default=0.0, min_value=0.0, max_value=1.0)

        # Get extracted data from context
        extracted_data = self._get_extracted_data()
        if extracted_data is None:
            logger.error("ai_validate: No extracted data found in ctx.results['ai_extracted_data']")
            report = self._create_report(
                passed=False,
                confidence=0.0,
                sku_match=False,
                missing_fields=[],
                errors=["No extracted data found in context"],
                warnings=[],
            )
            self._store_results(report)
            return report

        # Get query SKU
        query_sku = self._get_query_sku()

        # Build validation report
        report = self._validate(
            extracted_data=extracted_data,
            query_sku=query_sku,
            required_fields=required_fields,
            sku_must_match=sku_must_match,
            min_confidence=min_confidence,
        )

        self._store_results(report)

        logger.info(
            "ai_validate: Validation %s (confidence: %.3f, sku_match: %s, errors: %d)",
            "PASSED" if report["passed"] else "FAILED",
            report["confidence"],
            report["sku_match"],
            len(report["errors"]),
        )

        return report

    def _validate(
        self,
        extracted_data: dict[str, Any],
        query_sku: str | None,
        required_fields: list[str],
        sku_must_match: bool,
        min_confidence: float,
    ) -> dict[str, Any]:
        """
        Perform validation and build the validation report.

        Args:
            extracted_data: The AI-extracted data to validate
            query_sku: The SKU we were searching for
            required_fields: List of required field names
            sku_must_match: Whether to validate SKU matching
            min_confidence: Minimum required confidence score

        Returns:
            Validation report dictionary
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Extract confidence from data
        confidence = self._extract_confidence(extracted_data)

        # Validate required fields
        missing_fields = self._validate_required_fields(extracted_data, required_fields)
        if missing_fields:
            errors.append(f"Missing required fields: {', '.join(missing_fields)}")

        # Validate confidence threshold
        confidence_passed = confidence >= min_confidence
        if not confidence_passed:
            errors.append(f"Confidence too low: {confidence:.3f} (minimum: {min_confidence:.3f})")

        # Validate SKU matching
        sku_match = True
        if sku_must_match and query_sku:
            extracted_sku = self._extract_sku(extracted_data)
            if extracted_sku:
                sku_match = self._fuzzy_sku_match(query_sku, extracted_sku)
                if not sku_match:
                    errors.append(f"SKU mismatch: expected '{query_sku}', found '{extracted_sku}'")
            else:
                warnings.append("No SKU found in extracted data for matching validation")
                # SKU matching was requested but no SKU found - this is a soft failure
                if sku_must_match:
                    sku_match = False
        elif sku_must_match and not query_sku:
            warnings.append("sku_must_match=True but no query SKU available in context")

        # Determine overall pass/fail
        passed = not missing_fields and confidence_passed and sku_match

        return self._create_report(
            passed=passed,
            confidence=confidence,
            sku_match=sku_match,
            missing_fields=missing_fields,
            errors=errors,
            warnings=warnings,
        )

    def _get_extracted_data(self) -> dict[str, Any] | None:
        """Get extracted data from context."""
        data = self.ctx.results.get("ai_extracted_data")
        if isinstance(data, dict):
            return data
        return None

    def _get_query_sku(self) -> str | None:
        """Get query SKU from results or context."""
        # Try results first
        sku = self.ctx.results.get("sku")
        if isinstance(sku, str) and sku.strip():
            return sku.strip()

        # Fallback to context
        sku = self.ctx.context.get("sku")
        if isinstance(sku, str) and sku.strip():
            return sku.strip()

        return None

    def _extract_confidence(self, data: dict[str, Any]) -> float:
        """Extract confidence score from extracted data."""
        # Check for explicit _confidence field
        confidence = data.get("_confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            return float(confidence)

        # Try other common confidence field names
        for field in ["confidence", "score", "certainty"]:
            value = data.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)

        # Default: calculate from field completeness
        return self._calculate_completeness_confidence(data)

    def _calculate_completeness_confidence(self, data: dict[str, Any]) -> float:
        """Calculate a basic confidence score based on field completeness."""
        # Skip internal fields
        skip_fields = {"_confidence", "_source_url", "confidence", "score"}
        fields = [k for k in data.keys() if k not in skip_fields]

        if not fields:
            return 0.0

        present = 0
        for field in fields:
            value = data.get(field)
            if value is not None and (not isinstance(value, str) or value.strip()):
                present += 1

        return present / len(fields)

    def _extract_sku(self, data: dict[str, Any]) -> str | None:
        """Extract SKU from extracted data using common field names."""
        sku_fields = ["sku", "SKU", "upc", "UPC", "mpn", "MPN", "part_number", "item_number"]

        for field in sku_fields:
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _validate_required_fields(self, data: dict[str, Any], required_fields: list[str]) -> list[str]:
        """Validate that all required fields are present and non-empty."""
        missing: list[str] = []

        for field in required_fields:
            value = data.get(field)
            if value is None:
                missing.append(field)
            elif isinstance(value, str) and not value.strip():
                missing.append(field)
            elif isinstance(value, list) and len(value) == 0:
                missing.append(field)
            elif isinstance(value, dict) and len(value) == 0:
                missing.append(field)

        return missing

    def _fuzzy_sku_match(self, query_sku: str, extracted_sku: str) -> bool:
        """
        Perform fuzzy SKU matching.

        Handles:
        - Case-insensitive comparison
        - Whitespace normalization
        - Partial match tolerance (80% similarity)
        - Leading zero handling

        Args:
            query_sku: The SKU we searched for
            extracted_sku: The SKU found in the data

        Returns:
            True if SKUs match with sufficient confidence
        """
        # Normalize both SKUs
        query_normalized = query_sku.lower().strip()
        extracted_normalized = extracted_sku.lower().strip()

        # Direct match after normalization
        if query_normalized == extracted_normalized:
            return True

        # Remove leading zeros and compare
        query_no_zeros = query_normalized.lstrip("0") or "0"
        extracted_no_zeros = extracted_normalized.lstrip("0") or "0"
        if query_no_zeros == extracted_no_zeros:
            return True

        # Fuzzy matching using SequenceMatcher
        # Require 80% similarity for a match
        similarity = SequenceMatcher(None, query_normalized, extracted_normalized).ratio()
        if similarity >= 0.8:
            return True

        # Check if one contains the other (handles partial matches)
        if query_normalized in extracted_normalized or extracted_normalized in query_normalized:
            # Require minimum length to avoid false positives
            if len(query_normalized) >= 6 or len(extracted_normalized) >= 6:
                return True

        return False

    def _create_report(
        self,
        passed: bool,
        confidence: float,
        sku_match: bool,
        missing_fields: list[str],
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        """Create the validation report structure."""
        return {
            "passed": passed,
            "confidence": round(confidence, 3),
            "sku_match": sku_match,
            "missing_fields": missing_fields,
            "errors": errors,
            "warnings": warnings,
        }

    def _store_results(self, report: dict[str, Any]) -> None:
        """Store validation results in context."""
        self.ctx.results["validation_passed"] = report["passed"]
        self.ctx.results["validation_errors"] = report["errors"]
        self.ctx.results["validation_report"] = report

    # Type coercion helpers

    def _coerce_list(self, value: Any) -> list[str]:
        """Coerce value to list of strings."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        if isinstance(value, str):
            # Handle comma-separated string
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _coerce_bool(self, value: Any) -> bool:
        """Coerce value to boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y")
        return bool(value)

    def _coerce_float(
        self,
        value: Any,
        default: float,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> float:
        """Coerce value to float with bounds."""
        try:
            if isinstance(value, bool):
                raise ValueError("bool not allowed")
            if isinstance(value, (int, float)):
                coerced = float(value)
            elif isinstance(value, str):
                coerced = float(value.strip())
            else:
                coerced = default
        except (ValueError, TypeError):
            coerced = default

        if min_value is not None:
            coerced = max(min_value, coerced)
        if max_value is not None:
            coerced = min(max_value, coerced)

        return coerced
