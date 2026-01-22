"""
Config Fetcher - Fetch latest published config from API and validate.

This module provides functions to:
- Fetch latest published config from the runner-facing API endpoint
- Validate response against full Pydantic ScraperConfig model
- Fail fast with clear error messages on validation failure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from scraper_backend.scrapers.models.config import ScraperConfig

if TYPE_CHECKING:
    from scraper_backend.core.api_client import ScraperAPIClient

logger = logging.getLogger(__name__)


class ConfigFetchError(Exception):
    """Raised when config fetch fails."""

    def __init__(
        self,
        message: str,
        config_slug: str | None = None,
        schema_version: str | None = None,
        original_error: Exception | None = None,
    ):
        self.config_slug = config_slug
        self.schema_version = schema_version
        self.original_error = original_error
        super().__init__(message)


class ConfigValidationError(Exception):
    """Raised when config validation fails."""

    def __init__(
        self,
        message: str,
        config_slug: str,
        schema_version: str,
        validation_errors: list[dict[str, Any]],
    ):
        self.config_slug = config_slug
        self.schema_version = schema_version
        self.validation_errors = validation_errors
        full_message = (
            f"{message} (slug={config_slug}, schema_version={schema_version})"
        )
        super().__init__(full_message)


@dataclass
class PublishedConfig:
    """Published config response from API."""

    schema_version: str
    slug: str
    version_number: int
    status: str
    config: dict[str, Any]
    published_at: str
    published_by: str


def fetch_published_config(
    api_client: "ScraperAPIClient", slug: str
) -> PublishedConfig:
    """
    Fetch the latest published config for a scraper from the API.

    Args:
        api_client: The API client instance
        slug: The scraper slug (e.g., 'hobby-lobby', 'amazon')

    Returns:
        PublishedConfig with the config data

    Raises:
        ConfigFetchError: If the config cannot be fetched (not found, auth error, etc.)
    """
    try:
        response = api_client._make_request(
            "GET", f"/api/internal/scraper-configs/{slug}"
        )

        return PublishedConfig(
            schema_version=response["schema_version"],
            slug=response["slug"],
            version_number=response["version_number"],
            status=response["status"],
            config=response["config"],
            published_at=response["published_at"],
            published_by=response["published_by"],
        )

    except KeyError as e:
        raise ConfigFetchError(
            f"Invalid response format from API for slug '{slug}': missing key {e}",
            config_slug=slug,
        ) from e
    except Exception as e:
        raise ConfigFetchError(
            f"Failed to fetch config for slug '{slug}': {e}",
            config_slug=slug,
            original_error=e,
        ) from e


def validate_config(
    published_config: PublishedConfig,
) -> ScraperConfig:
    """
    Validate a published config against the full Pydantic ScraperConfig model.

    This validation happens BEFORE any expensive runner work (browser startup, etc.)

    Args:
        published_config: The published config to validate

    Returns:
        Validated ScraperConfig Pydantic model

    Raises:
        ConfigValidationError: If validation fails with detailed error info
    """
    try:
        config = ScraperConfig(**published_config.config)
        logger.info(
            f"[ConfigFetcher] Validated config for {published_config.slug} "
            f"(schema_version={published_config.schema_version}, "
            f"version={published_config.version_number})"
        )
        return config

    except ValidationError as e:
        errors = [
            {
                "loc": err["loc"],
                "msg": err["msg"],
                "type": err["type"],
            }
            for err in e.errors()
        ]

        logger.error(
            f"[ConfigFetcher] Config validation failed for {published_config.slug} "
            f"(schema_version={published_config.schema_version}): {errors}"
        )

        raise ConfigValidationError(
            f"Config validation failed for '{published_config.slug}' "
            f"(schema_version={published_config.schema_version}): {len(errors)} error(s)",
            config_slug=published_config.slug,
            schema_version=published_config.schema_version,
            validation_errors=errors,
        )


def fetch_and_validate_config(
    api_client: "ScraperAPIClient", slug: str
) -> tuple[PublishedConfig, ScraperConfig]:
    """
    Fetch and validate a scraper config in one operation.

    This is the main entry point for the runner to get a validated config.

    Args:
        api_client: The API client instance
        slug: The scraper slug

    Returns:
        Tuple of (PublishedConfig metadata, validated ScraperConfig model)

    Raises:
        ConfigFetchError: If the config cannot be fetched
        ConfigValidationError: If the config fails validation
    """
    published_config = fetch_published_config(api_client, slug)
    validated_config = validate_config(published_config)
    return published_config, validated_config


@dataclass
class JobStartupError(Exception):
    """Raised when job startup fails due to config issues."""

    job_id: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
