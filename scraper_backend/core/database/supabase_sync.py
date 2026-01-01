import logging
import os
from typing import Any, cast

from supabase import Client, create_client
from supabase.lib.client_options import ClientOptions

logger = logging.getLogger(__name__)


class SupabaseSync:
    """Handles synchronization with Supabase (PostgreSQL)."""

    def __init__(self):
        self._client: Client | None = None
        self._initialized = False

    def initialize(self, settings_manager: Any = None) -> bool:
        """Initialize Supabase client if enabled and configured."""
        if self._initialized:
            return True

        # Use passed settings manager or try import (fallback)
        sm = settings_manager
        if not sm:
            try:
                from scraper_backend.core.settings_manager import settings
                sm = settings
            except ImportError:
                 logger.warning("Could not import settings for SupabaseSync")
                 return False

        if not sm.get("supabase_enabled"):
            return False

        url = sm.get("supabase_url")
        key = sm.get("supabase_key")

        if not url or not key:
            logger.warning("Supabase enabled but URL or Key not configured.")
            return False

        try:
            # Increase timeout for potential slow queries
            self._client = create_client(url, key)
            self._initialized = True
            logger.info("Supabase initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Supabase: {e}")
            return False

    def _get_client(self) -> Client | None:
        if not self.initialize():
            return None
        return self._client

    # =========================================================================
    # Product Operations
    # =========================================================================

    def update_product_input(self, sku: str, data: dict) -> bool:
        """Update product input data. Sets pipeline_status='staging'."""
        client = self._get_client()
        if not client:
            return False

        try:
            # Check if exists
            res = client.table("products").select("sku").eq("sku", sku).execute()
            exists = len(res.data) > 0

            payload: dict[str, Any] = {
                "sku": sku,
                "input": data,
                "pipeline_status": "staging",
                "updated_at": "now()",
            }

            if exists:
                client.table("products").update(cast(dict[str, Any], payload)).eq(
                    "sku", sku
                ).execute()
            else:
                client.table("products").insert(cast(dict[str, Any], payload)).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to update product input {sku}: {e}")
            return False

    def update_product_source(self, sku: str, source_name: str, data: dict) -> bool:
        """Update a specific scraper source result. Sets pipeline_status='scraped' unless currently 'staging'."""
        client = self._get_client()
        if not client:
            return False

        try:
            # Need to fetch existing sources and status first to merge, or use a jsonb update if supported easily
            # Supabase/Postgrest doesn't support partial JSON updates easily without a function or fetching first.
            # We'll fetch first.
            res = (
                client.table("products").select("sources, pipeline_status").eq("sku", sku).execute()
            )

            current_sources: dict[str, Any] = {}
            current_status: str | None = None

            if res.data:
                first_row = cast(dict[str, Any], res.data[0])
                current_sources = first_row.get("sources") or {}
                current_status = first_row.get("pipeline_status")
            else:
                logger.warning(
                    f"Product {sku} not found in database when updating source {source_name}. Creating new entry."
                )

            current_sources[source_name] = data

            # Status Transition Logic:
            # 1. If currently 'staging', move to 'scraped' (now that we have results)
            # 2. If currently 'scraped', KEEP 'scraped'
            # 3. If currently 'consolidated' or 'approved', KEEP it (prevent regression)
            # 4. If new/unknown/null, set to 'scraped' (Default for new discoveries)

            valid_statuses = ["staging", "scraped", "consolidated", "approved", "published"]

            if current_status == "staging":
                new_status = "scraped"
            elif current_status is not None and current_status in valid_statuses:
                new_status = str(current_status)
            else:
                new_status = "scraped"

            payload: dict[str, Any] = {
                "sku": sku,  # In case we need to insert
                "sources": current_sources,
                "pipeline_status": new_status,
                "updated_at": "now()",
            }

            if res.data:
                client.table("products").update(cast(dict[str, Any], payload)).eq(
                    "sku", sku
                ).execute()
            else:
                client.table("products").insert(cast(dict[str, Any], payload)).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to update product source {sku}: {e}")
            return False

    def update_product_consolidated(self, sku: str, data: dict) -> bool:
        """Update consolidated data. Sets pipeline_status='consolidated'."""
        client = self._get_client()
        if not client:
            return False

        try:
            payload: dict[str, Any] = {
                "consolidated": data,
                "pipeline_status": "consolidated",
                "updated_at": "now()",
            }
            client.table("products").update(cast(dict[str, Any], payload)).eq("sku", sku).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to update product consolidated {sku}: {e}")
            return False

    def get_products_by_status(self, status: str | None = None) -> list[dict]:
        """Fetch products, optionally filtered by status."""
        client = self._get_client()
        if not client:
            return []

        try:
            query = client.table("products").select("*")
            if status:
                query = query.eq("pipeline_status", status)

            # Limit for safety?
            res = query.limit(500).execute()
            return cast(list[dict[str, Any]], res.data)
        except Exception as e:
            logger.error(f"Failed to fetch products: {e}")
            return []

    def get_product(self, sku: str) -> dict | None:
        """Fetch a single product by SKU."""
        client = self._get_client()
        if not client:
            return None

        try:
            res = client.table("products").select("*").eq("sku", sku).single().execute()
            return cast(dict[str, Any] | None, res.data)
        except Exception as e:
            logger.error(f"Failed to fetch product {sku}: {e}")
            return None

    # Legacy alias
    sync_staging_product = update_product_input

    def sync_staging_batch(self, products: list[dict]) -> int:
        """Batch sync input products."""
        client = self._get_client()
        if not client:
            return 0

        count = 0
        try:
            # Prepare batch upserts
            batch_data = []
            for p in products:
                sku = p.get("sku") or p.get("SKU")
                if not sku:
                    continue

                batch_data.append(
                    {"sku": sku, "input": p, "pipeline_status": "staging", "updated_at": "now()"}
                )

            # Upsert efficiently
            if batch_data:
                # Chunking might be needed for very large batches
                chunk_size = 100
                for i in range(0, len(batch_data), chunk_size):
                    chunk = batch_data[i : i + chunk_size]
                    client.table("products").upsert(chunk).execute()
                    count += len(chunk)

            return count
        except Exception as e:
            logger.error(f"Failed to sync staging batch: {e}")
            return 0

    def sync_scraper_result(self, sku: str, scraper_name: str, data: dict) -> bool:
        return self.update_product_source(sku, scraper_name, data)

    def sync_consolidation_state(self, sku: str, data: dict) -> bool:
        return self.update_product_consolidated(sku, data)

    def get_all_staging_products(self) -> list[dict]:
        return self.get_products_by_status("staging")

    def delete_product(self, sku: str) -> bool:
        """Delete a product."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.table("products").delete().eq("sku", sku).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete product {sku}: {e}")
            return False

    # =========================================================================
    # Scraper Configuration Methods
    # =========================================================================

    def get_scraper(self, name: str) -> dict | None:
        """Get a single scraper configuration."""
        client = self._get_client()
        if not client:
            return None
        try:
            res = client.table("scrapers").select("*").eq("name", name).execute()
            if res.data:
                return cast(dict[str, Any], res.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get scraper {name}: {e}")
            return None

    def get_all_scrapers(self, include_disabled: bool = True) -> list[dict]:
        """Get all scraper configurations."""
        client = self._get_client()
        if not client:
            return []
        try:
            query = client.table("scrapers").select("*")
            if not include_disabled:
                query = query.eq("disabled", False)
            res = query.execute()
            return cast(list[dict[str, Any]], res.data)
        except Exception as e:
            logger.error(f"Failed to get scrapers: {e}")
            return []

    def save_scraper(self, name: str, config: dict) -> bool:
        """Save/update a scraper configuration."""
        client = self._get_client()
        if not client:
            return False
        try:
            config["name"] = name
            config["updated_at"] = "now()"

            # Upsert
            client.table("scrapers").upsert(config).execute()
            logger.info(f"Saved scraper config: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save scraper {name}: {e}")
            return False

    def delete_scraper(self, name: str) -> bool:
        """Delete a scraper configuration."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.table("scrapers").delete().eq("name", name).execute()
            logger.info(f"Deleted scraper: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete scraper {name}: {e}")
            return False

    def update_scraper_health(self, name: str, health: dict) -> bool:
        """Update scraper health status."""
        client = self._get_client()
        if not client:
            return False
        try:
            update_data = {
                "status": health.get("status", "unknown"),
                "last_tested": health.get("last_tested"),
                "test_results": {
                    "selectors_passed": health.get("selectors_passed", 0),
                    "selectors_total": health.get("selectors_total", 0),
                    "test_skus_passed": health.get("test_skus_passed", 0),
                    "test_skus_total": health.get("test_skus_total", 0),
                },
                "updated_at": "now()",
            }

            # Map selector statuses
            if "selectors" in health:
                selector_statuses = []
                for sel in health.get("selectors", []):
                    selector_statuses.append(
                        {
                            "name": sel.get("name"),
                            "status": sel.get("status", "unknown"),
                            "last_value": sel.get("value"),
                            "success_count": sel.get("success_count", 0),
                            "fail_count": sel.get("fail_count", 0),
                        }
                    )
                update_data["selector_statuses"] = selector_statuses

            client.table("scrapers").update(update_data).eq("name", name).execute()
            logger.info(f"Updated health for scraper: {name} -> {health.get('status')}")
            return True
        except Exception as e:
            logger.error(f"Failed to update scraper health {name}: {e}")
            return False

    def update_scraper_test_result(self, name: str, result_data: dict) -> bool:
        """
        Update the last test result for a scraper.

        Args:
            name: Scraper name
            result_data: Dictionary containing timestamp, skus, selectors, etc.
        """
        client = self._get_client()
        if not client:
            return False

        try:
            update_data: dict[str, Any] = {"last_test_result": result_data, "updated_at": "now()"}

            client.table("scrapers").update(cast(dict[str, Any], update_data)).eq(
                "name", name
            ).execute()
            logger.info(f"Saved test results for scraper: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save test results for {name}: {e}")
            return False

    def toggle_scraper(self, name: str, disabled: bool) -> bool:
        """Enable or disable a scraper."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.table("scrapers").update({"disabled": disabled, "updated_at": "now()"}).eq(
                "name", name
            ).execute()

            status = "disabled" if disabled else "enabled"
            logger.info(f"Scraper {name} {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to toggle scraper {name}: {e}")
            return False

    # =========================================================================
    # Scrape Tracking Methods (product_scraped_sites)
    # =========================================================================

    def record_scrape_status(
        self,
        sku: str,
        scraper_name: str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        """
        Record or update the scrape status for a SKU/scraper combination.

        Args:
            sku: Product SKU
            scraper_name: Name of the scraper
            status: One of 'pending', 'scraped', 'not_found', 'error'
            error_message: Optional error message if status is 'error'

        Returns:
            True if successful, False otherwise
        """
        client = self._get_client()
        if not client:
            return False

        try:
            payload: dict[str, Any] = {
                "sku": sku,
                "scraper_name": scraper_name,
                "status": status,
                "updated_at": "now()",
            }

            if status in ("scraped", "not_found", "error", "no_results"):
                payload["last_scraped_at"] = "now()"

            # Set error_message (None is valid for clearing)
            payload["error_message"] = error_message

            # Upsert based on unique (sku, scraper_name) constraint
            client.table("product_scraped_sites").upsert(
                cast(dict[str, Any], payload), on_conflict="sku,scraper_name"
            ).execute()

            logger.debug(f"Recorded scrape status: {sku}/{scraper_name} -> {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to record scrape status {sku}/{scraper_name}: {e}")
            return False

    def initialize_sku_scrapes(self, sku: str, scraper_names: list[str]) -> int:
        """
        Initialize pending scrape records for a SKU when it enters staging.

        Args:
            sku: Product SKU
            scraper_names: List of scraper names to initialize

        Returns:
            Number of records created
        """
        client = self._get_client()
        if not client:
            return 0

        try:
            records = [
                {"sku": sku, "scraper_name": name, "status": "pending"} for name in scraper_names
            ]

            if records:
                # Upsert to handle re-initialization gracefully
                client.table("product_scraped_sites").upsert(
                    records, on_conflict="sku,scraper_name"
                ).execute()

            logger.info(f"Initialized {len(records)} scrape records for SKU: {sku}")
            return len(records)
        except Exception as e:
            logger.error(f"Failed to initialize scrapes for {sku}: {e}")
            return 0

    def get_scrape_history(self, sku: str) -> list[dict]:
        """
        Get all scrape records for a SKU.

        Args:
            sku: Product SKU

        Returns:
            List of scrape records with scraper_name, status, last_scraped_at, etc.
        """
        client = self._get_client()
        if not client:
            return []

        try:
            res = (
                client.table("product_scraped_sites")
                .select("*")
                .eq("sku", sku)
                .order("scraper_name")
                .execute()
            )
            return cast(list[dict[str, Any]], res.data)
        except Exception as e:
            logger.error(f"Failed to get scrape history for {sku}: {e}")
            return []

    def get_pending_scrapes(self, sku: str) -> list[str]:
        """
        Get list of scraper names that haven't run yet for a SKU.

        Args:
            sku: Product SKU

        Returns:
            List of scraper names with 'pending' status
        """
        client = self._get_client()
        if not client:
            return []

        try:
            res = (
                client.table("product_scraped_sites")
                .select("scraper_name")
                .eq("sku", sku)
                .eq("status", "pending")
                .execute()
            )
            return [cast(dict[str, Any], r)["scraper_name"] for r in res.data]
        except Exception as e:
            logger.error(f"Failed to get pending scrapes for {sku}: {e}")
            return []

    def get_products_not_scraped_by(self, scraper_name: str) -> list[str]:
        """
        Get SKUs that haven't been successfully scraped by a specific scraper.

        Args:
            scraper_name: Name of the scraper

        Returns:
            List of SKUs with 'pending' or 'error' status for this scraper
        """
        client = self._get_client()
        if not client:
            return []

        try:
            res = (
                client.table("product_scraped_sites")
                .select("sku")
                .eq("scraper_name", scraper_name)
                .in_("status", ["pending", "error"])
                .execute()
            )
            return [cast(dict[str, Any], r)["sku"] for r in res.data]
        except Exception as e:
            logger.error(f"Failed to get products not scraped by {scraper_name}: {e}")
            return []

    def get_scrape_stats(self, sku: str) -> dict:
        """
        Get aggregated scrape statistics for a SKU.

        Args:
            sku: Product SKU

        Returns:
            Dictionary with counts per status
        """
        client = self._get_client()
        if not client:
            return {}

        try:
            res = client.table("product_scraped_sites").select("status").eq("sku", sku).execute()

            stats = {"pending": 0, "scraped": 0, "not_found": 0, "error": 0, "no_results": 0, "total": 0}
            for r in res.data:
                row = cast(dict[str, Any], r)
                status = str(row.get("status", "pending"))
                if status in stats:
                    stats[status] = int(stats[status]) + 1
                stats["total"] = int(stats["total"]) + 1

            return stats
        except Exception as e:
            logger.error(f"Failed to get scrape stats for {sku}: {e}")
            return {}

    # =========================================================================
    # App Settings (Secure Storage)
    # =========================================================================

    def get_all_settings(self) -> dict[str, Any]:
        """
        Get all application settings from the database.
        Returns:
            Dictionary of {key: {"value": str, "encrypted": bool}}
        """
        client = self._get_client()
        if not client:
            return {}
        
        try:
            res = client.table("app_settings").select("*").execute()
            data = {}
            for row in res.data:
                data[row["key"]] = {
                    "value": row["value"],
                    "encrypted": row.get("encrypted", False)
                }
            return data
        except Exception as e:
            logger.error(f"Failed to get app settings: {e}")
            return {}

    def save_setting(self, key: str, value: str, encrypted: bool = False) -> bool:
        """
        Save a setting to the database.
        
        Args:
            key: Setting key
            value: Setting value (string)
            encrypted: Whether the value is encrypted
        """
        client = self._get_client()
        if not client:
            return False
            
        try:
            payload = {
                "key": key,
                "value": value,
                "encrypted": encrypted,
                "updated_at": "now()"
            }
            client.table("app_settings").upsert(payload).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to save app setting {key}: {e}")
            return False


# Global instance
supabase_sync = SupabaseSync()
