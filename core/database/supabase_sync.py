from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SupabaseSyncStub:
    """
    Stub for legacy direct-database access pattern.

    Per coordinator-runner architecture, scrapers should NOT access the database
    directly. All data should flow through the API client callbacks.
    This stub exists for backward compatibility and logs deprecation warnings.
    """

    def __init__(self) -> None:
        self._warned = False

    def _warn_once(self, method: str) -> None:
        if not self._warned:
            logger.warning(f"supabase_sync.{method}() called - this is deprecated. Scrapers should use APIClient callbacks instead of direct DB access.")
            self._warned = True

    def record_scrape_result(
        self,
        sku: str,
        scraper_name: str,
        status: str,
        data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        self._warn_once("record_scrape_result")
        logger.debug(f"[stub] record_scrape_result: {scraper_name}/{sku} = {status}")
        return True

    def get_pending_skus(self, limit: int = 100) -> list[str]:
        self._warn_once("get_pending_skus")
        return []

    def update_scraper_status(self, scraper_name: str, status: str) -> bool:
        self._warn_once("update_scraper_status")
        return True

    def sync_scraper_configs(self, configs: list[dict]) -> bool:
        self._warn_once("sync_scraper_configs")
        return True

    def get_scraper_config(self, name: str) -> dict[str, Any] | None:
        self._warn_once("get_scraper_config")
        return None

    def record_scrape_status(self, sku: str, scraper_name: str, status: str, error_message: str | None = None) -> None:
        """Record scrape status for tracking."""
        self._warn_once("record_scrape_status")


supabase_sync = SupabaseSyncStub()
