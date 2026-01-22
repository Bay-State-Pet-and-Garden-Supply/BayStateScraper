#!/usr/bin/env python3
"""
Migrate YAML scraper configs to database.

This script:
1. Loads YAML configs from BayStateScraper/scrapers/configs/
2. Normalizes them by adding schema_version
3. Validates against the canonical schema
4. Inserts/updates into the database via Supabase
5. Creates published versions

Usage:
    python -m tools.migrate_configs [--dry-run] [--verbose] [--limit N]
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

import yaml
from pydantic import ValidationError

# Add scraper_backend to path for schema imports
_scraper_backend_path = Path(__file__).resolve().parent.parent / "scraper_backend"
if str(_scraper_backend_path) not in sys.path:
    sys.path.insert(0, str(_scraper_backend_path))

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
CONFIGS_DIR = Path(__file__).parent.parent / "scrapers" / "configs"
OUTPUT_DIR = Path(__file__).parent.parent / "tools"
SCHEMA_VERSION = "1.0"


class MigrationError(Exception):
    """Raised when migration fails for a config."""

    pass


class ConfigNormalizer:
    """Normalize YAML config to canonical schema."""

    # Maps old field names to new field names (if any)
    FIELD_MAPPINGS = {
        # No mappings needed - YAML fields match schema field names
    }

    # Default values for optional fields
    DEFAULTS = {
        "selectors": [],
        "workflows": [],
        "normalization": None,
        "login": None,
        "timeout": 30,
        "retries": 3,
        "image_quality": 50,
        "anti_detection": None,
        "http_status": None,
        "validation": None,
        "test_skus": [],
        "fake_skus": [],
        "edge_case_skus": None,
        "display_name": None,
    }

    def __init__(self, yaml_path: Path):
        self.yaml_path = yaml_path
        self.yaml_data: dict[str, Any] = {}
        self.errors: list[str] = []

    def load(self) -> bool:
        """Load YAML file."""
        try:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                self.yaml_data = yaml.safe_load(f) or {}
            logger.debug(
                f"Loaded {self.yaml_path.name}: {len(self.yaml_data)} top-level keys"
            )
            return True
        except FileNotFoundError:
            self.errors.append(f"File not found: {self.yaml_path}")
            return False
        except yaml.YAMLError as e:
            self.errors.append(f"YAML parse error: {e}")
            return False

    def normalize(self) -> dict[str, Any]:
        """Normalize YAML data to canonical schema."""
        normalized = {}

        # Add schema_version (this is the key migration step)
        normalized["schema_version"] = SCHEMA_VERSION

        # Copy known fields
        for field in [
            "name",
            "display_name",
            "base_url",
            "selectors",
            "workflows",
            "normalization",
            "login",
            "timeout",
            "retries",
            "image_quality",
            "anti_detection",
            "http_status",
            "validation",
            "test_skus",
            "fake_skus",
            "edge_case_skus",
        ]:
            if field in self.yaml_data:
                normalized[field] = self.yaml_data[field]
            elif field in self.DEFAULTS:
                normalized[field] = self.DEFAULTS[field]

        # Validate name field (required)
        if "name" not in self.yaml_data or not self.yaml_data["name"]:
            self.errors.append("Missing required field: name")

        # Validate base_url (required)
        if "base_url" not in self.yaml_data or not self.yaml_data["base_url"]:
            self.errors.append("Missing required field: base_url")

        return normalized

    def _get_scraper_config(self):
        """Import and return ScraperConfig class using importlib for reliability."""
        import importlib.util

        scraper_backend_path = (
            Path(__file__).resolve().parent.parent
            / "scraper_backend"
            / "scrapers"
            / "models"
            / "config.py"
        )

        if not scraper_backend_path.exists():
            raise ModuleNotFoundError(
                f"ScraperConfig not found at {scraper_backend_path}"
            )

        spec = importlib.util.spec_from_file_location(
            "scraper_config", scraper_backend_path
        )
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError("Could not load ScraperConfig module")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module.SraperConfig

    def validate(self, config_data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate normalized config against Pydantic schema."""
        try:
            ScraperConfig = self._get_scraper_config()
            ScraperConfig(**config_data)
            return True, []
        except ValidationError as e:
            errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            return False, errors
        except (ModuleNotFoundError, AttributeError) as e:
            return True, [f"WARNING: Schema validation skipped - {e}"]


class MigrationResult:
    """Result of migrating a single config."""

    def __init__(self, yaml_path: Path):
        self.yaml_path = yaml_path
        self.slug = yaml_path.stem
        self.success = False
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.config_id: Union[str, None] = None
        self.version_id: Union[str, None] = None
        self.normalized_data: Union[dict[str, Any], None] = None


class ConfigMigrator:
    """Main migration orchestrator."""

    def __init__(
        self,
        supabase_url: Union[str, None] = None,
        supabase_key: Union[str, None] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ):
        self.dry_run = dry_run
        self.verbose = verbose
        self.results: list[MigrationResult] = []
        self.supabase = None

        if supabase_url and supabase_key:
            try:
                from supabase import create_client

                self.supabase = create_client(supabase_url, supabase_key)
                logger.info("Connected to Supabase")
            except ImportError:
                logger.warning(
                    "Supabase client not installed, DB writes will be skipped"
                )
            except Exception as e:
                logger.warning(f"Failed to connect to Supabase: {e}")

    def discover_yaml_configs(self) -> list[Path]:
        """Find all YAML config files."""
        yaml_files = list(CONFIGS_DIR.glob("*.yaml")) + list(CONFIGS_DIR.glob("*.yml"))
        logger.info(f"Discovered {len(yaml_files)} YAML configs in {CONFIGS_DIR}")
        return sorted(yaml_files)

    def migrate_config(self, yaml_path: Path) -> MigrationResult:
        """Migrate a single YAML config to DB."""
        result = MigrationResult(yaml_path)

        if self.verbose:
            logger.info(f"Processing: {yaml_path.name}")

        # Step 1: Load YAML
        normalizer = ConfigNormalizer(yaml_path)
        if not normalizer.load():
            result.errors.extend(normalizer.errors)
            return result

        # Step 2: Normalize
        normalized = normalizer.normalize()
        if normalizer.errors:
            result.warnings.extend(normalizer.errors)
        result.normalized_data = normalized

        # Step 3: Validate against schema
        valid, validation_errors = normalizer.validate(normalized)
        if not valid:
            result.errors.extend(validation_errors)
            return result

        # Step 4: Insert to DB
        if self.supabase:
            try:
                db_result = self._insert_to_db(result, normalized)
                result.config_id = db_result.get("config_id")
                result.version_id = db_result.get("version_id")
                result.success = True
                logger.info(
                    f"Migrated {result.slug}: config_id={result.config_id}, version_id={result.version_id}"
                )
            except Exception as e:
                result.errors.append(f"DB insert failed: {e}")
        else:
            # Dry run or no Supabase - just log success
            result.success = True
            logger.info(
                f"[DRY RUN] Would migrate {result.slug}: {json.dumps(normalized, indent=2, default=str)[:200]}..."
            )

        return result

    def _insert_to_db(
        self, result: MigrationResult, config_data: dict[str, Any]
    ) -> dict[str, str]:
        """Insert or update config in database."""
        slug = result.slug

        # Check if config already exists
        existing = (
            self.supabase.table("scrapers")
            .select("id, config")
            .eq("name", slug)
            .execute()
        )

        config_json = json.dumps(config_data, default=str)
        now = datetime.now(timezone.utc).isoformat()

        if existing.data:
            # Update existing config
            config_id = existing.data[0]["id"]
            logger.debug(f"Updating existing config: {slug} (id={config_id})")

            # Update the config
            self.supabase.table("scrapers").update(
                {
                    "config": config_json,
                    "updated_at": now,
                    "status": "active",  # Mark as active after migration
                }
            ).eq("id", config_id).execute()

            return {"config_id": config_id, "version_id": "n/a (in-place update)"}
        else:
            # Insert new config
            logger.debug(f"Creating new config: {slug}")

            insert_data = {
                "name": slug,
                "display_name": config_data.get("display_name")
                or slug.replace("-", " ").title(),
                "base_url": config_data["base_url"],
                "config": config_json,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }

            result = self.supabase.table("scrapers").insert(insert_data).execute()
            config_id = result.data[0]["id"]

            return {"config_id": config_id, "version_id": "n/a (new config)"}

    def run(self, limit: Union[int, None] = None) -> list[MigrationResult]:
        """Run migration on all YAML configs."""
        yaml_files = self.discover_yaml_configs()

        if limit:
            yaml_files = yaml_files[:limit]
            logger.info(f"Limited to {limit} configs")

        for yaml_path in yaml_files:
            result = self.migrate_config(yaml_path)
            self.results.append(result)

        return self.results

    def generate_report(self) -> str:
        """Generate migration report."""
        successful = [r for r in self.results if r.success]
        failed = [r for r in self.results if not r.success]

        lines = [
            "# Migration Report",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Summary",
            f"- Total configs: {len(self.results)}",
            f"- Successful: {len(successful)}",
            f"- Failed: {len(failed)}",
            "",
        ]

        if successful:
            lines.extend(
                [
                    "## Successful Migrations",
                    "",
                ]
            )
            for r in successful:
                lines.append(f"- **{r.slug}**: config_id={r.config_id}")
            lines.append("")

        if failed:
            lines.extend(
                [
                    "## Failed Migrations",
                    "",
                ]
            )
            for r in failed:
                lines.append(f"- **{r.slug}**:")
                for err in r.errors:
                    lines.append(f"  - ERROR: {err}")
            lines.append("")

        return "\n".join(lines)


def run_migration(
    supabase_url: Union[str, None] = None,
    supabase_key: Union[str, None] = None,
    dry_run: bool = False,
    verbose: bool = False,
    limit: Union[int, None] = None,
    output_report: Union[Path, None] = None,
) -> list[MigrationResult]:
    """Run the full migration."""
    migrator = ConfigMigrator(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        dry_run=dry_run,
        verbose=verbose,
    )

    results = migrator.run(limit=limit)

    # Generate and optionally save report
    report = migrator.generate_report()
    print(report)

    if output_report:
        output_report.write_text(report)
        logger.info(f"Report saved to: {output_report}")

    return results


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate YAML scraper configs to database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to database, just validate and report",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Limit number of configs to migrate",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None, help="Output report to file"
    )
    parser.add_argument(
        "--supabase-url",
        type=str,
        default=None,
        help="Supabase project URL (or set SUPABASE_URL env var)",
    )
    parser.add_argument(
        "--supabase-key",
        type=str,
        default=None,
        help="Supabase service role key (or set SUPABASE_SERVICE_KEY env var)",
    )

    args = parser.parse_args()

    supabase_url = args.supabase_url or (
        None if args.dry_run else __import__("os").environ.get("SUPABASE_URL")
    )
    supabase_key = args.supabase_key or (
        None if args.dry_run else __import__("os").environ.get("SUPABASE_SERVICE_KEY")
    )

    if not args.dry_run and not supabase_url:
        logger.warning("No Supabase URL provided. Will run in dry-run mode.")
        args.dry_run = True

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    results = run_migration(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        dry_run=args.dry_run,
        verbose=args.verbose,
        limit=args.limit,
        output_report=args.output,
    )

    # Exit with error code if any failed
    failed = [r for r in results if not r.success]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
