"""
Config Validator - YAML schema validation before execution.

Provides comprehensive validation of scraper configuration files with:
- Schema validation using Pydantic models
- Action name validation (checks registered actions)
- Selector reference validation
- Detailed error messages with context
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, errors: list[str] | None = None):
        self.message = message
        self.errors = errors or []
        super().__init__(message)


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config_name: str | None = None
    file_path: str | None = None

    def __str__(self) -> str:
        status = "VALID" if self.valid else "INVALID"
        lines = [f"Validation Result: {status}"]
        if self.config_name:
            lines.append(f"Config: {self.config_name}")
        if self.file_path:
            lines.append(f"File: {self.file_path}")
        if self.errors:
            lines.append(f"Errors ({len(self.errors)}):")
            for err in self.errors:
                lines.append(f"  - {err}")
        if self.warnings:
            lines.append(f"Warnings ({len(self.warnings)}):")
            for warn in self.warnings:
                lines.append(f"  - {warn}")
        return "\n".join(lines)


class ConfigValidator:
    """
    Validates scraper configuration files before execution.

    Performs:
    - YAML syntax validation
    - Pydantic schema validation (ScraperConfig)
    - Action name validation (checks against registered actions)
    - Selector reference validation (extract actions reference valid selectors)
    - Best practice warnings
    """

    # Known valid action names (from ActionRegistry)
    KNOWN_ACTIONS = {
        "navigate",
        "wait",
        "wait_for",
        "click",
        "conditional_click",
        "input_text",
        "extract",
        "extract_single",
        "extract_multiple",
        "extract_and_transform",
        "extract_from_json",
        "check_no_results",
        "conditional_skip",
        "verify",
        "scroll",
        "login",
        "anti_detection",
        "combine",
        "conditional",
        "image",
        "json",
        "script",
        "sponsored",
        "table",
        "transform",
        "validation",
        "weight",
    }

    def __init__(self, strict: bool = False):
        """
        Initialize the config validator.

        Args:
            strict: If True, treat warnings as errors
        """
        self.strict = strict
        self._registered_actions: set[str] | None = None

    def _get_registered_actions(self) -> set[str]:
        """Get dynamically registered actions from ActionRegistry."""
        if self._registered_actions is not None:
            return self._registered_actions

        try:
            from scrapers.actions import ActionRegistry

            ActionRegistry.auto_discover_actions()
            self._registered_actions = set(
                ActionRegistry.get_registered_actions().keys()
            )
            return self._registered_actions
        except ImportError:
            logger.warning("Could not import ActionRegistry, using static action list")
            return self.KNOWN_ACTIONS

    def validate_file(self, file_path: str | Path) -> ValidationResult:
        """
        Validate a YAML configuration file.

        Args:
            file_path: Path to the YAML configuration file

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        file_path = Path(file_path)
        errors: list[str] = []
        warnings: list[str] = []
        config_name: str | None = None

        # Check file exists
        if not file_path.exists():
            return ValidationResult(
                valid=False,
                errors=[f"File not found: {file_path}"],
                file_path=str(file_path),
            )

        # Parse YAML
        try:
            with open(file_path, encoding="utf-8") as f:
                config_dict = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return ValidationResult(
                valid=False,
                errors=[f"YAML parse error: {e}"],
                file_path=str(file_path),
            )

        if not config_dict:
            return ValidationResult(
                valid=False,
                errors=["Empty configuration file"],
                file_path=str(file_path),
            )

        config_name = config_dict.get("name", "unknown")

        # Validate structure
        structure_result = self._validate_structure(config_dict)
        errors.extend(structure_result["errors"])
        warnings.extend(structure_result["warnings"])

        # Validate using Pydantic schema
        schema_result = self._validate_schema(config_dict)
        errors.extend(schema_result["errors"])
        warnings.extend(schema_result["warnings"])

        # Validate workflow actions
        action_result = self._validate_actions(config_dict)
        errors.extend(action_result["errors"])
        warnings.extend(action_result["warnings"])

        # Validate selector references
        selector_result = self._validate_selectors(config_dict)
        errors.extend(selector_result["errors"])
        warnings.extend(selector_result["warnings"])

        # Best practice checks
        bp_result = self._check_best_practices(config_dict)
        warnings.extend(bp_result["warnings"])
        if self.strict:
            errors.extend(bp_result["warnings"])

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            config_name=config_name,
            file_path=str(file_path),
        )

    def validate_dict(self, config_dict: dict[str, Any]) -> ValidationResult:
        """
        Validate a configuration dictionary.

        Args:
            config_dict: Configuration dictionary

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        errors: list[str] = []
        warnings: list[str] = []
        config_name = config_dict.get("name", "unknown")

        # Validate structure
        structure_result = self._validate_structure(config_dict)
        errors.extend(structure_result["errors"])
        warnings.extend(structure_result["warnings"])

        # Validate using Pydantic schema
        schema_result = self._validate_schema(config_dict)
        errors.extend(schema_result["errors"])
        warnings.extend(schema_result["warnings"])

        # Validate workflow actions
        action_result = self._validate_actions(config_dict)
        errors.extend(action_result["errors"])
        warnings.extend(action_result["warnings"])

        # Validate selector references
        selector_result = self._validate_selectors(config_dict)
        errors.extend(selector_result["errors"])
        warnings.extend(selector_result["warnings"])

        # Best practice checks
        bp_result = self._check_best_practices(config_dict)
        warnings.extend(bp_result["warnings"])
        if self.strict:
            errors.extend(bp_result["warnings"])

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            config_name=config_name,
        )

    def validate_yaml_string(self, yaml_string: str) -> ValidationResult:
        """
        Validate a YAML string.

        Args:
            yaml_string: YAML configuration as string

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        try:
            config_dict = yaml.safe_load(yaml_string)
        except yaml.YAMLError as e:
            return ValidationResult(
                valid=False,
                errors=[f"YAML parse error: {e}"],
            )

        if not config_dict:
            return ValidationResult(
                valid=False,
                errors=["Empty configuration"],
            )

        return self.validate_dict(config_dict)

    def _validate_structure(self, config_dict: dict[str, Any]) -> dict[str, list[str]]:
        """Validate basic structure requirements."""
        errors: list[str] = []
        warnings: list[str] = []

        # Required top-level fields
        required_fields = ["name", "base_url"]
        for field in required_fields:
            if field not in config_dict:
                errors.append(f"Missing required field: '{field}'")
            elif not config_dict[field]:
                errors.append(f"Required field '{field}' is empty")

        # Workflows should exist (even if empty)
        if "workflows" not in config_dict:
            warnings.append(
                "No 'workflows' defined - scraper will not perform any actions"
            )
        elif not config_dict["workflows"]:
            warnings.append(
                "'workflows' is empty - scraper will not perform any actions"
            )

        return {"errors": errors, "warnings": warnings}

    def _validate_schema(self, config_dict: dict[str, Any]) -> dict[str, list[str]]:
        """Validate against Pydantic schema."""
        errors: list[str] = []
        warnings: list[str] = []

        try:
            from core.anti_detection_manager import AntiDetectionConfig
            from scrapers.models import ScraperConfig

            # Preprocess anti_detection if present
            config_copy = config_dict.copy()
            if "anti_detection" in config_copy and isinstance(
                config_copy["anti_detection"], dict
            ):
                config_copy["anti_detection"] = AntiDetectionConfig(
                    **config_copy["anti_detection"]
                )

            # Remove empty login if present
            if "login" in config_copy and not config_copy["login"]:
                del config_copy["login"]

            # Validate
            ScraperConfig(**config_copy)

        except ImportError as e:
            warnings.append(f"Could not import schema models for validation: {e}")
        except Exception as e:
            error_msg = str(e)
            # Parse Pydantic validation errors for better messages
            if "validation error" in error_msg.lower():
                # Extract field-specific errors
                for line in error_msg.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("For further"):
                        errors.append(f"Schema error: {line}")
            else:
                errors.append(f"Schema validation failed: {error_msg}")

        return {"errors": errors, "warnings": warnings}

    def _validate_actions(self, config_dict: dict[str, Any]) -> dict[str, list[str]]:
        """Validate workflow action names."""
        errors: list[str] = []
        warnings: list[str] = []

        workflows = config_dict.get("workflows", [])
        if not workflows:
            return {"errors": errors, "warnings": warnings}

        registered_actions = self._get_registered_actions()

        for i, step in enumerate(workflows, 1):
            if not isinstance(step, dict):
                errors.append(
                    f"Step {i}: Invalid step format (expected dict, got {type(step).__name__})"
                )
                continue

            action = step.get("action")
            if not action:
                errors.append(f"Step {i}: Missing 'action' field")
                continue

            action_lower = action.lower()
            if (
                action_lower not in registered_actions
                and action_lower not in self.KNOWN_ACTIONS
            ):
                errors.append(f"Step {i}: Unknown action '{action}'")

            # Validate action-specific params
            params = step.get("params", {})
            action_errors = self._validate_action_params(action_lower, params, i)
            errors.extend(action_errors)

        return {"errors": errors, "warnings": warnings}

    def _validate_action_params(
        self, action: str, params: dict[str, Any], step_num: int
    ) -> list[str]:
        """Validate action-specific parameters."""
        errors: list[str] = []

        # Action-specific parameter requirements
        if action == "navigate":
            if "url" not in params:
                errors.append(
                    f"Step {step_num}: 'navigate' action requires 'url' parameter"
                )

        elif action == "click":
            if "selector" not in params:
                errors.append(
                    f"Step {step_num}: 'click' action requires 'selector' parameter"
                )

        elif action == "wait_for":
            if "selector" not in params:
                errors.append(
                    f"Step {step_num}: 'wait_for' action requires 'selector' parameter"
                )

        elif action == "input_text":
            if "selector" not in params:
                errors.append(
                    f"Step {step_num}: 'input_text' action requires 'selector' parameter"
                )
            if "text" not in params and "value" not in params:
                errors.append(
                    f"Step {step_num}: 'input_text' action requires 'text' or 'value' parameter"
                )

        elif action == "conditional_skip":
            if "if_flag" not in params:
                errors.append(
                    f"Step {step_num}: 'conditional_skip' action requires 'if_flag' parameter"
                )

        elif action == "extract":
            if "fields" not in params:
                errors.append(
                    f"Step {step_num}: 'extract' action requires 'fields' parameter"
                )

        elif action == "verify":
            if "selector" not in params:
                errors.append(
                    f"Step {step_num}: 'verify' action requires 'selector' parameter"
                )
            if "expected_value" not in params:
                errors.append(
                    f"Step {step_num}: 'verify' action requires 'expected_value' parameter"
                )

        return errors

    def _validate_selectors(self, config_dict: dict[str, Any]) -> dict[str, list[str]]:
        """Validate selector definitions and references."""
        errors: list[str] = []
        warnings: list[str] = []

        selectors = config_dict.get("selectors", [])
        selector_names: set[str] = set()
        selector_ids: set[str] = set()

        # Build selector lookup
        for i, sel in enumerate(selectors):
            if not isinstance(sel, dict):
                errors.append(f"Selector {i + 1}: Invalid format (expected dict)")
                continue

            name = sel.get("name")
            if not name:
                errors.append(f"Selector {i + 1}: Missing 'name' field")
            else:
                if name in selector_names:
                    warnings.append(f"Duplicate selector name: '{name}'")
                selector_names.add(name)

            sel_id = sel.get("id")
            if sel_id:
                if sel_id in selector_ids:
                    errors.append(f"Duplicate selector ID: '{sel_id}'")
                selector_ids.add(sel_id)

            if "selector" not in sel:
                errors.append(f"Selector '{name or i + 1}': Missing 'selector' field")

        # Check extract action references
        workflows = config_dict.get("workflows", [])
        for i, step in enumerate(workflows, 1):
            if not isinstance(step, dict):
                continue

            action = step.get("action", "").lower()
            params = step.get("params", {})

            if action == "extract":
                fields = params.get("fields", [])
                for field in fields:
                    if isinstance(field, str):
                        if field not in selector_names and field not in selector_ids:
                            warnings.append(
                                f"Step {i}: 'extract' references undefined selector '{field}'"
                            )

        return {"errors": errors, "warnings": warnings}

    def _check_best_practices(
        self, config_dict: dict[str, Any]
    ) -> dict[str, list[str]]:
        """Check for best practices and common issues."""
        warnings: list[str] = []

        # Check for test_skus
        if "test_skus" not in config_dict:
            warnings.append("No 'test_skus' defined - consider adding for testing")

        # Check for validation section
        if "validation" not in config_dict:
            warnings.append(
                "No 'validation' section - consider adding no_results detection"
            )

        # Check timeout
        timeout = config_dict.get("timeout", 30)
        if timeout < 5:
            warnings.append(f"Timeout of {timeout}s may be too short for some sites")
        elif timeout > 120:
            warnings.append(
                f"Timeout of {timeout}s is very long - may cause slow failures"
            )

        # Check retries
        retries = config_dict.get("retries", 3)
        if retries < 1:
            warnings.append("No retries configured - failures will not be retried")
        elif retries > 10:
            warnings.append(
                f"High retry count ({retries}) may cause very long execution times"
            )

        # Check for wait_for after navigate
        workflows = config_dict.get("workflows", [])
        for i, step in enumerate(workflows):
            if not isinstance(step, dict):
                continue

            action = step.get("action", "").lower()
            if action == "navigate" and i + 1 < len(workflows):
                next_step = workflows[i + 1]
                if isinstance(next_step, dict):
                    next_action = next_step.get("action", "").lower()
                    if next_action not in ["wait", "wait_for"]:
                        warnings.append(
                            f"Step {i + 1}: 'navigate' not followed by wait - page may not be loaded"
                        )

        return {"errors": [], "warnings": warnings}


def validate_config_file(
    file_path: str | Path, strict: bool = False
) -> ValidationResult:
    """
    Convenience function to validate a config file.

    Args:
        file_path: Path to YAML config file
        strict: Treat warnings as errors

    Returns:
        ValidationResult
    """
    validator = ConfigValidator(strict=strict)
    return validator.validate_file(file_path)


def validate_all_configs(
    configs_dir: str | Path, strict: bool = False
) -> dict[str, ValidationResult]:
    """
    Validate all YAML configs in a directory.

    Args:
        configs_dir: Directory containing YAML config files
        strict: Treat warnings as errors

    Returns:
        Dict mapping filename to ValidationResult
    """
    configs_dir = Path(configs_dir)
    results: dict[str, ValidationResult] = {}
    validator = ConfigValidator(strict=strict)

    for yaml_file in configs_dir.glob("*.yaml"):
        results[yaml_file.name] = validator.validate_file(yaml_file)

    return results
