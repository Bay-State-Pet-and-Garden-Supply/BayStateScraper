"""
Result Collector Module

Collects scraper results and syncs to Supabase or local JSON file.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scraper_backend.core.models import RawScrapedProduct

logger = logging.getLogger(__name__)


class ResultCollector:
    """Utility class to collect and store scraper results in Supabase or local JSON."""

    def __init__(self, output_dir: str | None = None, test_mode: bool = False) -> None:
        """Initialize result collector."""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results: dict[str, dict[str, Any]] = {}
        self._supabase: Any = None  # SupabaseSync or None
        self._supabase_initialized = False
        self._local_json_path: Path | None = None

        # Determine output directory for local fallback
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            # Default to data/scraper_sessions in project root or /app/data in Docker
            project_root = Path(__file__).parent.parent.parent
            self._output_dir = project_root / "data" / "scraper_sessions"

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self.test_mode = test_mode

    def _get_supabase(self):
        """Lazy initialize Supabase connection. Returns None if unavailable."""
        if self._supabase is not None:
            return self._supabase

        if self._supabase_initialized:
            # Already tried and failed
            return None

        try:
            from scraper_backend.core.database.supabase_sync import supabase_sync

            if supabase_sync.initialize():
                self._supabase = supabase_sync
                self._supabase_initialized = True
                logger.info("Supabase initialized for result collection")
                return self._supabase
        except ImportError:
            logger.info("supabase package not installed, using local JSON storage")
        except Exception as e:
            logger.warning(f"Supabase not available: {e}")

        self._supabase_initialized = True  # Mark as tried
        return None

    def _save_result_to_local(self, sku: str, scraper_name: str, data: dict) -> None:
        """Save a single result to the local JSON session file."""
        if self._local_json_path is None:
            self._local_json_path = self._output_dir / f"session_{self.session_id}.json"

        # Load existing data or start fresh
        existing_data: dict[str, Any] = {"session_id": self.session_id, "results": {}}
        if self._local_json_path.exists():
            try:
                with open(self._local_json_path) as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                pass

        # Add/update result
        if scraper_name not in existing_data["results"]:
            existing_data["results"][scraper_name] = {}
        existing_data["results"][scraper_name][sku] = {
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        # Write back
        with open(self._local_json_path, "w") as f:
            json.dump(existing_data, f, indent=2, default=str)

    def add_result(
        self,
        sku: str,
        scraper_name: str,
        result_data: dict[str, Any] | RawScrapedProduct,
        image_quality: int = 50,
    ) -> None:
        """
        Add a scraper result. Syncs directly to Supabase.

        Args:
            sku: Product SKU
            scraper_name: Name of the scraper that produced this result
            result_data: Either a raw dict or RawScrapedProduct instance
            image_quality: Quality score for images (0-100)
        """
        from scraper_backend.core.models import RawScrapedProduct

        try:
            timestamp = datetime.now().isoformat()

            # Normalize to RawScrapedProduct for validation
            if isinstance(result_data, dict):
                # Normalize image field names (some configs use "Image URLs" instead of "Images")
                images = (
                    result_data.get("Images")
                    or result_data.get("Image URLs")
                    or result_data.get("Image_URLs")
                    or []
                )
                product = RawScrapedProduct(
                    sku=sku,
                    source=scraper_name,
                    name=result_data.get("Name"),
                    brand=result_data.get("Brand"),
                    weight=result_data.get("Weight"),
                    description=result_data.get("Description"),
                    images=images,
                    category=result_data.get("Category"),
                    product_type=result_data.get("ProductType"),
                    scraped_price=result_data.get("Price"),
                    image_quality=image_quality,
                )
                data_for_db = product.to_db_dict()
            else:
                product = result_data
                data_for_db = product.to_db_dict()

            # Check if we actually found product data
            has_data = any(
                data_for_db.get(field) for field in ["Name", "Brand", "ScrapedPrice", "Weight"]
            )

            if not has_data:
                logger.debug(f"No data found for {sku} from {scraper_name}")
                return

            # In test mode, we only keep results in memory for stats
            if self.test_mode:
                # Keep in memory for stats
                if scraper_name not in self.results:
                    self.results[scraper_name] = {}

                self.results[scraper_name][sku] = {
                    "sku": sku,
                    "scraper": scraper_name,
                    "timestamp": timestamp,
                    "data": data_for_db,
                    "image_quality": product.image_quality,
                }
                return

            # Sync to Supabase or local JSON
            supabase = self._get_supabase()
            if supabase:
                try:
                    # supabase_sync methods are synchronous
                    success = supabase.update_product_source(sku, scraper_name, data_for_db)
                    if success:
                        logger.info(f"Synced {sku} from {scraper_name} to Supabase")
                    else:
                        logger.warning(
                            f"Supabase sync returned False for {sku}, falling back to local"
                        )
                        self._save_result_to_local(sku, scraper_name, data_for_db)
                except Exception as e:
                    logger.error(f"Supabase sync failed for {sku}: {e}")
                    # Fallback to local JSON on failure
                    self._save_result_to_local(sku, scraper_name, data_for_db)
            else:
                # Use local JSON storage
                self._save_result_to_local(sku, scraper_name, data_for_db)

            # Keep in memory for stats
            if scraper_name not in self.results:
                self.results[scraper_name] = {}

            self.results[scraper_name][sku] = {
                "sku": sku,
                "scraper": scraper_name,
                "timestamp": timestamp,
                "data": data_for_db,
                "image_quality": product.image_quality,
            }

        except Exception as e:
            logger.error(f"Error processing result: {e}")

    def save_session(self, metadata: dict[str, Any] | None = None) -> str:
        """
        Save session results.
        If Supabase is active, data is already synced.
        If not, save to local JSON file.
        """
        if self._supabase_initialized:
            return f"supabase://session/{self.session_id}"

        if self.test_mode:
            logger.info("Test mode: Skipping session save to disk")
            return "TEST_MODE_NO_SAVE"

        # Fallback to local file storage
        import json
        import os

        # Ensure data directory exists
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(project_root, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Create output file
        filename = f"scraper_results_{self.session_id}.json"
        filepath = os.path.join(data_dir, filename)

        output_data = {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "results": self.results,
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, sort_keys=True, default=str)
            logger.info(f"Saved results to local file: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save local results file: {e}")
            return ""

    def get_results_by_sku(self, sku: str) -> dict[str, Any]:
        """Get results from memory (current session only)."""
        results = {}
        for scraper_name, scraper_results in self.results.items():
            if sku in scraper_results:
                results[scraper_name] = scraper_results[sku]
        return results

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about collected results in current session."""
        total_results = sum(len(r) for r in self.results.values())
        all_skus: set[str] = set()
        for scraper_results in self.results.values():
            all_skus.update(scraper_results.keys())

        # Count SKUs found on multiple sites
        sku_counts: dict[str, int] = {}
        for scraper_results in self.results.values():
            for sku in scraper_results:
                sku_counts[sku] = sku_counts.get(sku, 0) + 1
        multi_site = sum(1 for count in sku_counts.values() if count > 1)

        return {
            "total_unique_skus": len(all_skus),
            "total_results": total_results,
            "scrapers_used": list(self.results.keys()),
            "skus_found_on_multiple_sites": multi_site,
            "session_id": self.session_id,
            "storage": "supabase" if self._supabase_initialized else "memory_only",
        }
