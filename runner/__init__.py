from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.api_client import JobConfig
from core.events import create_emitter
from core.settings_manager import settings
from scrapers.executor.workflow_executor import WorkflowExecutor
from scrapers.parser import ScraperConfigParser
from scrapers.result_collector import ResultCollector

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    pass


def create_log_entry(level: str, message: str) -> dict[str, Any]:
    return {
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def run_job(
    job_config: JobConfig,
    runner_name: str | None = None,
    log_buffer: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del runner_name

    job_id = job_config.job_id
    emitter = create_emitter(job_id)
    parser = ScraperConfigParser()
    collector = ResultCollector(test_mode=job_config.test_mode)

    results: dict[str, Any] = {
        "skus_processed": 0,
        "scrapers_run": [],
        "data": {},
    }

    if log_buffer is None:
        log_buffer = []

    log_buffer.append(create_log_entry("info", f"Job {job_id} started"))
    log_buffer.append(create_log_entry("info", f"Processing {len(job_config.skus)} SKUs with {len(job_config.scrapers)} scrapers"))
    log_buffer.append(create_log_entry("info", f"Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}"))

    logger.info(f"[Runner] Starting job {job_id}")
    logger.info(f"[Runner] SKUs: {len(job_config.skus)}, Scrapers: {len(job_config.scrapers)}")
    logger.info(f"[Runner] Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}")

    configs: list[Any] = []
    config_errors: list[tuple[str, str]] = []

    # Get config directory path for fallback loading
    from pathlib import Path

    config_dir = Path(__file__).parent.parent / "scrapers" / "configs"

    for scraper_cfg in job_config.scrapers:
        try:
            options = scraper_cfg.options or {}
            config_dict = {
                "name": scraper_cfg.name,
                "base_url": scraper_cfg.base_url,
                "search_url_template": scraper_cfg.search_url_template,
                "selectors": scraper_cfg.selectors if scraper_cfg.selectors is not None else {},
                "workflows": options.get("workflows", []),
                "timeout": options.get("timeout", 30),
                "test_skus": scraper_cfg.test_skus if scraper_cfg.test_skus is not None else [],
                "retries": getattr(scraper_cfg, "retries", 0),
                "validation": getattr(scraper_cfg, "validation", None),
            }

            # Fallback to local YAML for validation config if not provided by API
            if config_dict.get("validation") is None:
                yaml_path = config_dir / f"{scraper_cfg.name.lower().replace(' ', '_')}.yaml"
                if yaml_path.exists():
                    try:
                        import yaml

                        with open(yaml_path, encoding="utf-8") as f:
                            yaml_config = yaml.safe_load(f)
                            if yaml_config and "validation" in yaml_config:
                                config_dict["validation"] = yaml_config["validation"]
                                logger.info(f"[Runner] Loaded validation config from local YAML: {scraper_cfg.name}")
                    except Exception as e:
                        logger.warning(f"[Runner] Failed to load validation from YAML for {scraper_cfg.name}: {e}")

            config = parser.load_from_dict(config_dict)
            configs.append(config)
            log_buffer.append(create_log_entry("info", f"Loaded scraper config: {config.name}"))
            logger.info(f"[Runner] Loaded scraper config: {config.name}")
        except Exception as e:
            config_errors.append((scraper_cfg.name, str(e)))
            log_buffer.append(create_log_entry("error", f"Failed to parse config for {scraper_cfg.name}: {e}"))
            logger.error(f"[Runner] Failed to parse config for {scraper_cfg.name}: {e}")

    if config_errors:
        error_details = "; ".join([f"{name}: {err}" for name, err in config_errors])
        log_buffer.append(create_log_entry("error", f"Configuration parsing failed for {len(config_errors)} scraper(s): {error_details}"))
        raise ConfigurationError(f"[Runner] Configuration parsing failed for {len(config_errors)} scraper(s): {error_details}")

    if not configs:
        log_buffer.append(create_log_entry("error", "No valid scraper configurations"))
        raise ConfigurationError("[Runner] No valid scraper configurations")

    skus = job_config.skus
    if not skus and job_config.test_mode:
        for config in configs:
            if hasattr(config, "test_skus") and config.test_skus:
                skus.extend(config.test_skus)
        skus = list(set(skus))
        log_buffer.append(create_log_entry("info", f"Test mode: using {len(skus)} test SKUs from configs"))
        logger.info(f"[Runner] Test mode: using {len(skus)} test SKUs from configs")

    if not skus:
        log_buffer.append(create_log_entry("warning", "No SKUs to process"))
        logger.warning("[Runner] No SKUs to process")
        return results

    for config in configs:
        log_buffer.append(create_log_entry("info", f"Starting scraper: {config.name}"))
        logger.info(f"[Runner] Running scraper: {config.name}")
        results["scrapers_run"].append(config.name)

        executor = None
        try:
            headless = settings.browser_settings["headless"]
            if not headless:
                logger.warning("[Runner] Running in VISIBLE mode (HEADLESS=false) - browser will be visible for debugging")
                log_buffer.append(create_log_entry("warning", "Running in VISIBLE mode - browser will be visible"))

            executor = WorkflowExecutor(
                config,
                headless=headless,
                timeout=30,
                worker_id="API",
                debug_mode=False,
                job_id=job_id,
                event_emitter=emitter,
            )

            # Run all async operations in a single event loop to properly manage
            # Playwright browser subprocess lifecycle
            async def run_all_scrapes():
                scrape_results = []
                try:
                    await executor.initialize()
                    for sku in skus:
                        try:
                            result = await executor.execute_workflow(
                                context={"sku": sku, "test_mode": job_config.test_mode},
                                quit_browser=False,
                            )
                            scrape_results.append((sku, result))
                        except Exception as e:
                            log_buffer.append(create_log_entry("error", f"{config.name}/{sku}: {type(e).__name__} - {e}"))
                            logger.error(f"[Runner] {config.name}/{sku}: Error - {e}")
                            scrape_results.append((sku, None))
                finally:
                    # Ensure browser is properly quit inside the async context
                    if executor.browser:
                        try:
                            await executor.browser.quit()
                        except Exception as e:
                            logger.debug(f"Browser quit error: {e}")
                return scrape_results

            scrape_results = asyncio.run(run_all_scrapes())

            # Process results after async loop completes
            for sku, result in scrape_results:
                if result is None:
                    continue

                results["skus_processed"] += 1

                if result.get("success"):
                    extracted_data = result.get("results", {})
                    has_data = any(extracted_data.get(field) for field in ["Name", "Brand", "Weight"])

                    if has_data:
                        if sku not in results["data"]:
                            results["data"][sku] = {}
                        results["data"][sku][config.name] = {
                            # Note: Price is NOT scraped - we use our own pricing
                            "title": extracted_data.get("Name"),
                            "brand": extracted_data.get("Brand"),
                            "weight": extracted_data.get("Weight"),
                            "description": extracted_data.get("Description"),
                            "images": extracted_data.get("Image URLs", []),
                            "availability": extracted_data.get("Availability"),
                            "url": extracted_data.get("URL"),
                            "scraped_at": datetime.now().isoformat(),
                        }

                        collector.add_result(sku, config.name, extracted_data)

                        log_buffer.append(create_log_entry("info", f"{config.name}/{sku}: Found data"))
                        logger.info(f"[Runner] {config.name}/{sku}: Found data")
                    else:
                        log_buffer.append(create_log_entry("info", f"{config.name}/{sku}: No data found"))
                        logger.info(f"[Runner] {config.name}/{sku}: No data found")
                else:
                    log_buffer.append(create_log_entry("warning", f"{config.name}/{sku}: Workflow failed"))
                    logger.warning(f"[Runner] {config.name}/{sku}: Workflow failed")

        except Exception as e:
            log_buffer.append(create_log_entry("error", f"Failed to initialize {config.name}: {e}"))
            logger.error(f"[Runner] Failed to initialize {config.name}: {e}")

    log_buffer.append(create_log_entry("info", f"Job complete. Processed {results['skus_processed']} SKUs"))
    logger.info(f"[Runner] Job complete. Processed {results['skus_processed']} SKUs")
    return results


__all__ = [
    "ConfigurationError",
    "create_emitter",
    "create_log_entry",
    "run_job",
]
