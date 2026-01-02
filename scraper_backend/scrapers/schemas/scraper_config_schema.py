from __future__ import annotations

import json

from scraper_backend.scrapers.models import ScraperConfig


def get_scraper_config_schema():
    """Generate JSON schema for ScraperConfig."""
    return ScraperConfig.model_json_schema()


def validate_config_dict(config_dict: dict) -> ScraperConfig:
    """Validate and parse a configuration dictionary into ScraperConfig."""
    return ScraperConfig(**config_dict)


if __name__ == "__main__":
    schema = get_scraper_config_schema()
    print(json.dumps(schema, indent=2))
