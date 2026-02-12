from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from scrapers.models.config import ScraperConfig

if TYPE_CHECKING:
    from core.api_client import ScraperAPIClient

logger = logging.getLogger(__name__)


class ConfigFetchError(Exception):
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
        full_message = f"{message} (slug={config_slug}, schema_version={schema_version})"
        super().__init__(full_message)


@dataclass
class PublishedConfig:
    schema_version: str
    slug: str
    version_number: int
    status: str
    config: dict[str, Any]
    published_at: str
    published_by: str


def fetch_published_config(api_client: "ScraperAPIClient", slug: str) -> PublishedConfig:
    try:
        response = api_client.get_published_config(slug)

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


def validate_config(published_config: PublishedConfig) -> ScraperConfig:
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

        logger.error(f"[ConfigFetcher] Config validation failed for {published_config.slug} (schema_version={published_config.schema_version}): {errors}")

        raise ConfigValidationError(
            f"Config validation failed for '{published_config.slug}' (schema_version={published_config.schema_version}): {len(errors)} error(s)",
            config_slug=published_config.slug,
            schema_version=published_config.schema_version,
            validation_errors=errors,
        )


def fetch_and_validate_config(api_client: "ScraperAPIClient", slug: str) -> tuple[PublishedConfig, ScraperConfig]:
    published_config = fetch_published_config(api_client, slug)
    validated_config = validate_config(published_config)
    return published_config, validated_config


@dataclass
class JobStartupError(Exception):
    job_id: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
