"""
Settings Manager for ProductScraper
Handles application configuration using JSON file-based storage and secure database storage.
"""
from __future__ import annotations


import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Use absolute import to avoid issues, but runtime import for circular dependencies
from utils.encryption import encryption_manager

logger = logging.getLogger(__name__)

# Handle PyInstaller bundle paths
if getattr(sys, "frozen", False):
    # Running in a PyInstaller bundle
    APPLICATION_PATH = Path(sys.executable).parent
    PROJECT_ROOT = APPLICATION_PATH
else:
    # Running in development
    PROJECT_ROOT = Path(__file__).parent.parent.parent  # src/core/ -> project root

# Settings cache for in-memory access
_settings_cache: dict[str, Any] = {}


class SettingsManager:
    """Manages application settings using JSON file-based storage."""

    # Default settings
    DEFAULTS = {
        # Scraper Credentials
        "petfoodex_username": "",
        "petfoodex_password": "",
        "phillips_username": "",
        "phillips_password": "",
        "orgill_username": "",
        "orgill_password": "",
        "shopsite_username": "",
        "shopsite_password": "",
        "scraper_system": "new",  # 'new' (modular YAML), 'legacy' (archived)
        # UI Settings
        "auto_scroll_logs": True,
        "theme": "dark",  # 'dark' or 'light'
        "max_workers": 2,  # Number of concurrent scrapers
        # Additional settings
        "selenium_timeout": 30,
        "openai_api_key": "",  # For OpenAI Batch API consolidation
        "classification_method": "llm",
        "auto_consolidate": False,
        # Supabase Settings
        "supabase_enabled": False,
        "supabase_url": "",
        "supabase_key": "",
    }

    def __init__(self) -> None:
        """Initialize settings manager with JSON file storage."""
        # Load .env variables
        load_dotenv()

        # Load from settings.json if it exists (for initial setup)
        self._load_from_json()

        # Load environment variables if they exist (for backward compatibility)
        self._load_from_env()

        # Load from remote database (Supabase) - requires Supabase credentials to be set first
        # We do this last so DB settings override local files/env (except for Supabase Connection itself)
        self._load_from_remote()

    def _load_from_remote(self) -> None:
        """Load encrypted settings from Supabase/PostgreSQL."""
        # Avoid circular import
        try:
             # Basic check to see if we can even try connecting
            if not self.get("supabase_enabled") or not self.get("supabase_url") or not self.get("supabase_key"):
                return

            from core.database.supabase_sync import supabase_sync
            
            # Ensure client is initialized
            if not supabase_sync.initialize(self):
                logger.warning("Supabase not initialized, skipping remote settings load.")
                return

            logger.info("Loading remote settings from database...")
            remote_settings = supabase_sync.get_all_settings()
            
            count = 0
            for key, data in remote_settings.items():
                value = data["value"]
                is_encrypted = data["encrypted"]
                
                if is_encrypted:
                    try:
                        decrypted = encryption_manager.decrypt(value)
                        if decrypted is not None:
                            value = decrypted
                        else:
                            logger.error(f"Failed to decrypt setting: {key}")
                            continue 
                    except Exception as e:
                        logger.error(f"Error decrypting {key}: {e}")
                        continue
                
                # Set the value in cache (overriding local)
                self.set(key, value)
                count += 1
            
            if count > 0:
                logger.info(f"Loaded {count} settings from database.")
                
        except ImportError as e:
            logger.warning(f"SupabaseSync not available (ImportError): {e}")
        except Exception as e:
            logger.error(f"Failed to load remote settings: {e}")

    def _load_from_json(self) -> None:
        """Load settings from settings.json file for initial setup."""
        try:
            settings_file = Path(__file__).parent.parent.parent / "settings.json"
            logger.info(f"Looking for settings at: {settings_file}")

            if settings_file.exists():
                with open(settings_file) as f:
                    json_settings = json.load(f)

                # Load values from JSON
                # In reload mode, we want to overwrite cache
                for key, value in json_settings.items():
                    self.set(key, value)

                # Log Supabase settings status
                has_supabase = bool(json_settings.get("supabase_enabled"))
                has_key = bool(json_settings.get("supabase_key"))
                logger.info(f"Settings loaded: supabase_enabled={has_supabase}, has_key={has_key}")
            else:
                logger.warning(f"Settings file not found at: {settings_file}")
        except Exception as e:
            logger.error(f"Failed to load settings from JSON: {e}")
            # Silently ignore JSON loading errors but log them
            pass

    def reload(self) -> None:
        """Force reload of settings from file and database."""
        self._load_from_json()
        self._load_from_env()
        self._load_from_remote()

    def _load_from_env(self) -> None:
        """Load settings from environment variables for backward compatibility."""
        env_mappings = {
            "petfoodex_username": "PETFOODEX_USERNAME",
            "petfoodex_password": "PETFOODEX_PASSWORD",
            "phillips_username": "PHILLIPS_USERNAME",
            "phillips_password": "PHILLIPS_PASSWORD",
            "orgill_username": "ORGILL_USERNAME",
            "orgill_password": "ORGILL_PASSWORD",
            "shopsite_username": "SHOPSITE_USERNAME",
            "shopsite_password": "SHOPSITE_PASSWORD",
            "browser_backend": "BROWSER_BACKEND",
            "supabase_enabled": "SUPABASE_ENABLED",
            "supabase_url": "SUPABASE_URL",
            "supabase_key": "SUPABASE_SERVICE_KEY",
            "openai_api_key": "OPENAI_API_KEY",
        }

        for setting_key, env_key in env_mappings.items():
            env_value = os.getenv(env_key)
            if env_value and not self.get(setting_key):
                self.set(setting_key, env_value)

        # Fallback for Supabase Key (Local .env uses ROLE_KEY, Docker uses SERVICE_KEY)
        if not self.get("supabase_key"):
            role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if role_key:
                self.set("supabase_key", role_key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        if default is None:
            default = self.DEFAULTS.get(key, "")

        # Get from cache
        value = _settings_cache.get(key, default)

        # Convert string booleans
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return value.lower() in ("true", "1")

        # Convert string numbers
        if isinstance(value, str) and value.isdigit():
            return int(value)

        return value

    def set(self, key: str, value: Any):
        """Set a setting value."""
        _settings_cache[key] = value

    def get_all(self) -> dict[str, Any]:
        """Get all settings as a dictionary."""
        all_settings = {}
        for key in self.DEFAULTS.keys():
            all_settings[key] = self.get(key)
        return all_settings

    def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        for key, value in self.DEFAULTS.items():
            self.set(key, value)

    def export_settings(self) -> dict[str, Any]:
        """Export settings for backup/sharing (excludes sensitive data)."""
        all_settings = self.get_all()
        # Remove sensitive data from export
        sensitive_keys = [
            "petfoodex_password",
            "phillips_password",
            "orgill_password",
            "shopsite_password",
            "supabase_key",
        ]
        for key in sensitive_keys:
            if key in all_settings:
                all_settings[key] = "***REDACTED***"
        return all_settings

    def import_settings(self, settings_dict: dict[str, Any]):
        """Import settings from a dictionary."""
        for key, value in settings_dict.items():
            if key in self.DEFAULTS and value != "***REDACTED***":
                self.set(key, value)

    def save(self) -> None:
        """Save current settings to settings.json."""
        try:
            settings_file = Path(__file__).parent.parent.parent / "settings.json"
            with open(settings_file, "w") as f:
                json.dump(_settings_cache, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise

    # Convenience methods for commonly accessed settings
    @property
    def petfoodex_credentials(self) -> tuple[str, str]:
        """Get Petfoodex credentials as (username, password)."""
        return self.get("petfoodex_username"), self.get("petfoodex_password")

    @property
    def phillips_credentials(self) -> tuple[str, str]:
        """Get Phillips credentials as (username, password)."""
        return self.get("phillips_username"), self.get("phillips_password")

    @property
    def orgill_credentials(self) -> tuple[str, str]:
        """Get Orgill credentials as (username, password)."""
        return self.get("orgill_username"), self.get("orgill_password")

    @property
    def shopsite_credentials(self) -> dict[str, str]:
        """Get ShopSite credentials as dictionary (HTTP Basic Auth)."""
        return {
            "username": self.get("shopsite_username"),
            "password": self.get("shopsite_password"),
        }

    @property
    def debug_mode(self) -> bool:
        """Get debug mode setting."""
        return bool(self.get("debug_mode"))

    @property
    def selenium_settings(self) -> dict[str, Any]:
        """Get Selenium settings."""
        return {
            "headless": True,
            "timeout": self.get("selenium_timeout"),
        }

    @property
    def auto_consolidate(self) -> bool:
        """Get auto-consolidate setting."""
        return bool(self.get("auto_consolidate"))


# Global settings instance
settings = SettingsManager()
