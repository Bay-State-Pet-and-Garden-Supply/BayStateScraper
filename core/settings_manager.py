"""
Settings Manager for BayStateScraper.

Simplified version that only handles runner API configuration.
Site credentials are now fetched on-demand from the coordinator API.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root directory - used by various modules for file paths
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class SettingsManager:
    """Manages runner configuration via environment variables."""

    DEFAULTS = {
        "max_workers": 2,
        "selenium_timeout": 30,
        "theme": "dark",
        "auto_scroll_logs": True,
    }

    def __init__(self) -> None:
        self._cache: dict = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        env_mappings = {
            "scraper_api_url": "SCRAPER_API_URL",
            "scraper_api_key": "SCRAPER_API_KEY",
            "runner_name": "RUNNER_NAME",
            "max_workers": "MAX_WORKERS",
            "selenium_timeout": "SELENIUM_TIMEOUT",
        }

        for setting_key, env_key in env_mappings.items():
            env_value = os.getenv(env_key)
            if env_value:
                self.set(setting_key, env_value)

    def get(self, key: str, default=None):
        if default is None:
            default = self.DEFAULTS.get(key, "")

        value = self._cache.get(key, default)

        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return value.lower() in ("true", "1")

        if isinstance(value, str) and value.isdigit():
            return int(value)

        return value

    def set(self, key: str, value):
        self._cache[key] = value

    def get_all(self) -> dict:
        all_settings = {}
        for key in self.DEFAULTS.keys():
            all_settings[key] = self.get(key)
        return all_settings

    def reload(self) -> None:
        self._load_from_env()

    @property
    def debug_mode(self) -> bool:
        return bool(self.get("debug_mode"))

    @property
    def selenium_settings(self) -> dict:
        return {
            "headless": True,
            "timeout": self.get("selenium_timeout"),
        }


settings = SettingsManager()
