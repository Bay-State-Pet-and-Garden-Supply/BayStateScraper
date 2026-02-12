from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.anti_detection_manager import AntiDetectionConfig


KNOWN_SCHEMA_VERSIONS = {"1.0"}


class SelectorConfig(BaseModel):
    """Configuration for CSS selectors used in scraping."""

    id: str | None = Field(None, description="Unique identifier for the selector (e.g., sel_abc123)")
    name: str = Field(..., description="Name of the field to extract")
    selector: str = Field(..., description="CSS selector for the field")
    attribute: str | None = Field(None, description="Attribute to extract (e.g., 'text', 'href', 'src')")
    multiple: bool = Field(False, description="Whether to extract multiple elements")
    required: bool = Field(True, description="Whether this field is required for a successful scrape")


class WorkflowStep(BaseModel):
    """A single step in the scraping workflow."""

    action: str = Field(..., description="Action type (e.g., 'navigate', 'click', 'wait', 'extract')")
    name: str | None = Field(None, description="Optional name for the step")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters for the action")


class LoginConfig(BaseModel):
    """Configuration for login handling."""

    url: str = Field(..., description="Login page URL")
    username_field: str = Field(..., description="CSS selector for username input")
    password_field: str = Field(..., description="CSS selector for password input")
    submit_button: str = Field(..., description="CSS selector for submit button")
    success_indicator: str | None = Field(None, description="CSS selector indicating successful login")
    failure_indicators: dict[str, Any] | None = Field(None, description="Indicators for detecting login failures")


class HttpStatusConfig(BaseModel):
    """Configuration for HTTP status code monitoring."""

    enabled: bool = Field(False, description="Whether to enable HTTP status monitoring")
    fail_on_error_status: bool = Field(True, description="Whether to fail workflow on 4xx/5xx status codes")
    error_status_codes: list[int] = Field(
        default_factory=lambda: [400, 401, 403, 404, 500, 502, 503, 504],
        description="HTTP status codes that should be considered errors",
    )
    warning_status_codes: list[int] = Field(
        default_factory=lambda: [301, 302, 307, 308],
        description="HTTP status codes that should generate warnings",
    )


class ValidationConfig(BaseModel):
    """Configuration for data validation and no-results detection."""

    no_results_selectors: list[str] | None = Field(None, description="Selectors to detect 'no results' pages")
    no_results_text_patterns: list[str] | None = Field(None, description="Text patterns to detect 'no results' pages")


class NormalizationRule(BaseModel):
    """Rule for normalizing extracted data."""

    field: str = Field(..., description="Name of the field to normalize")
    action: str = Field(
        ...,
        description="Normalization action (e.g., 'title_case', 'remove_prefix', 'trim')",
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters for the action")


class ScraperConfig(BaseModel):
    """Main configuration for a scraper."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    schema_version: str = Field(
        "1.0",
        description="Schema version for this config",
    )

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value not in KNOWN_SCHEMA_VERSIONS:
            known = ", ".join(sorted(KNOWN_SCHEMA_VERSIONS))
            raise ValueError(f"Unknown schema_version '{value}'. Known versions: {known}.")
        return value

    name: str = Field(..., description="Name of the scraper")
    base_url: str = Field(..., description="Base URL for the scraper")
    display_name: str | None = Field(None, description="Display name for UI")
    selectors: list[SelectorConfig] = Field(default_factory=list, description="List of selectors for data extraction")
    workflows: list[WorkflowStep] = Field(default_factory=list, description="List of workflow steps")
    normalization: list[NormalizationRule] | None = Field(None, description="List of normalization rules")
    login: LoginConfig | None = Field(None, description="Login configuration if required")
    timeout: int = Field(30, description="Default timeout in seconds", ge=1, le=300)
    retries: int = Field(3, description="Number of retries on failure", ge=0, le=10)
    anti_detection: AntiDetectionConfig | None = Field(None, description="Anti-detection configuration")
    http_status: HttpStatusConfig | None = Field(None, description="HTTP status monitoring configuration")
    validation: ValidationConfig | None = Field(None, description="Data validation and no-results configuration")
    test_skus: list[str] | None = Field(None, description="List of SKUs to use for testing")
    fake_skus: list[str] | None = Field(None, description="List of fake SKUs for no-results validation")
    edge_case_skus: list[str] | None = Field(None, description="List of edge case SKUs for boundary testing")
    image_quality: int = Field(50, description="Quality score for images (0-100)", ge=0, le=100)

    def requires_login(self) -> bool:
        """Check if this scraper requires authentication/login.

        Returns:
            True if login is required, False otherwise
        """
        # Check if login config is explicitly defined
        if self.login is not None:
            return True

        # Check workflow steps for login-related actions
        login_keywords = {"login", "authenticate", "sign_in", "signin", "password", "username"}
        for step in self.workflows:
            action_lower = step.action.lower()
            if any(keyword in action_lower for keyword in login_keywords):
                return True

            # Check params for credential-related fields
            if step.params:
                param_str = str(step.params).lower()
                if any(keyword in param_str for keyword in login_keywords):
                    return True

        return False
