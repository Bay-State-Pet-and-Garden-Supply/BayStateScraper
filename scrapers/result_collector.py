"""
Result Collector Module

Collects scraper results in memory for later submission via API callback.
No direct database access - all persistence goes through the coordinator.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.models import RawScrapedProduct

logger = logging.getLogger(__name__)


class ResultCollector:
    """Collects scraper results in memory for API submission."""

    def __init__(self, output_dir: str | None = None, test_mode: bool = False) -> None:
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results: dict[str, dict[str, Any]] = {}
        self.test_mode = test_mode

        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            project_root = Path(__file__).parent.parent.parent
            self._output_dir = project_root / "data" / "scraper_sessions"

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._local_json_path: Path | None = None

    def _save_result_to_local(self, sku: str, scraper_name: str, data: dict) -> None:
        if self._local_json_path is None:
            self._local_json_path = self._output_dir / f"session_{self.session_id}.json"

        existing_data: dict[str, Any] = {"session_id": self.session_id, "results": {}}
        if self._local_json_path.exists():
            try:
                with open(self._local_json_path) as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                pass

        if scraper_name not in existing_data["results"]:
            existing_data["results"][scraper_name] = {}
        existing_data["results"][scraper_name][sku] = {
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        with open(self._local_json_path, "w") as f:
            json.dump(existing_data, f, indent=2, default=str)

    def add_result(
        self,
        sku: str,
        scraper_name: str,
        result_data: dict[str, Any] | RawScrapedProduct,
        image_quality: int = 50,
    ) -> None:
        from core.models import RawScrapedProduct

        try:
            timestamp = datetime.now().isoformat()

            if isinstance(result_data, dict):
                images = result_data.get("Images") or result_data.get("Image URLs") or result_data.get("Image_URLs") or []
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

            has_data = any(data_for_db.get(field) for field in ["Name", "Brand", "ScrapedPrice", "Weight"])

            if not has_data:
                logger.debug(f"No data found for {sku} from {scraper_name}")
                return

            if scraper_name not in self.results:
                self.results[scraper_name] = {}

            self.results[scraper_name][sku] = {
                "sku": sku,
                "scraper": scraper_name,
                "timestamp": timestamp,
                "data": data_for_db,
                "image_quality": product.image_quality,
            }

            if not self.test_mode:
                self._save_result_to_local(sku, scraper_name, data_for_db)

        except Exception as e:
            logger.error(f"Error processing result: {e}")

    def save_session(self, metadata: dict[str, Any] | None = None) -> str:
        if self.test_mode:
            logger.info("Test mode: Skipping session save to disk")
            return "TEST_MODE_NO_SAVE"

        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root / "data"
        data_dir.mkdir(exist_ok=True)

        filename = f"scraper_results_{self.session_id}.json"
        filepath = data_dir / filename

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
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save local results file: {e}")
            return ""

    def get_results_by_sku(self, sku: str) -> dict[str, Any]:
        results = {}
        for scraper_name, scraper_results in self.results.items():
            if sku in scraper_results:
                results[scraper_name] = scraper_results[sku]
        return results

    def get_stats(self) -> dict[str, Any]:
        total_results = sum(len(r) for r in self.results.values())
        all_skus: set[str] = set()
        for scraper_results in self.results.values():
            all_skus.update(scraper_results.keys())

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
            "storage": "memory",
        }
