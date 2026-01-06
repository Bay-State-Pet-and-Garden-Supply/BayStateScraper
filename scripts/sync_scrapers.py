from __future__ import annotations

import os
import sys
import yaml
import logging
from pathlib import Path

# Setup paths
current_file = Path(__file__).resolve()
scripts_dir = current_file.parent
project_root = scripts_dir.parent

# Add project root to Python path
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.database.supabase_sync import supabase_sync
from utils.logger import setup_logging
from core.settings_manager import settings

logger = logging.getLogger(__name__)


def sync_scrapers():
    """Sync all YAML scraper configs to Supabase."""
    print("Starting scraper synchronization...")
    setup_logging()

    # Initialize Supabase
    if not settings.get("supabase_url") or not settings.get("supabase_key"):
        print("Error: Supabase credentials not found in settings or environment.")
        logger.error("Supabase credentials missing.")
        return

    if not supabase_sync.initialize():
        print("Error: Failed to connect to Supabase.")
        return

    configs_dir = project_root / "scrapers" / "configs"

    if not configs_dir.exists():
        print(f"Error: Configs directory not found at {configs_dir}")
        return

    yaml_files = list(configs_dir.glob("*.yaml"))
    print(f"Found {len(yaml_files)} config files in {configs_dir}")

    synced_count = 0
    failed_count = 0

    for yaml_file in yaml_files:
        if yaml_file.name == "sample_config.yaml":
            continue

        try:
            with open(yaml_file, "r") as f:
                config = yaml.safe_load(f)

            name = config.get("name")
            if not name:
                logger.warning(f"Skipping {yaml_file.name}: No name found in config")
                continue

            print(f"Syncing scraper: {name}...")

            # Ensure required fields and remove unknown columns
            if "status" not in config:
                config["status"] = "unknown"

            # Define allowed fields based on Supabase schema/frontend types
            ALLOWED_FIELDS = {
                "name",
                "display_name",
                "requires_auth",
                "url_template",
                "base_url",
                "test_skus",
                "fake_skus",
                "edge_case_skus",  # All SKU fields for testing
                "selectors",
                "workflows",
                "timeout",
                "status",
                "disabled",
                "last_tested",
                "test_results",
                "validation",
                "last_test_result",
                "login",
                "created_at",
                "updated_at",
            }

            # Filter config to only include allowed fields
            clean_config = {k: v for k, v in config.items() if k in ALLOWED_FIELDS}

            # Log dropped fields for visibility
            dropped = set(config.keys()) - ALLOWED_FIELDS
            if dropped:
                logger.info(f"Dropped non-schema fields for {name}: {dropped}")

            success = supabase_sync.save_scraper(name, clean_config)
            if success:
                print(f"✅ Successfully synced: {name}")
                synced_count += 1
            else:
                print(f"❌ Failed to sync: {name}")
                failed_count += 1

        except Exception as e:
            print(f"❌ Error processing {yaml_file.name}: {e}")
            logger.error(f"Error processing {yaml_file.name}: {e}")
            failed_count += 1

    print("-" * 40)
    print(f"Synchronization Complete.")
    print(f"Synced: {synced_count}")
    print(f"Failed: {failed_count}")


if __name__ == "__main__":
    sync_scrapers()
