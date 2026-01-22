"""
API-Driven Job Runner.

Entry point for running scrape jobs triggered by the BayStateApp coordinator API.
Fetches configuration from the API and submits results back via HTTP.

Usage (single job - for testing or legacy):
    python runner.py --job-id <uuid>

For production, use daemon.py instead which polls continuously.

Environment Variables:
    SCRAPER_API_URL: Base URL for BayStateApp API
    SCRAPER_API_KEY: API key for authentication
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.api_client import ScraperAPIClient, JobConfig
from core.events import create_emitter
from scrapers.parser import ScraperConfigParser
from scrapers.executor.workflow_executor import WorkflowExecutor
from scrapers.result_collector import ResultCollector
from utils.logger import NoHttpFilter, setup_logging

logger = logging.getLogger(__name__)


def run_job(job_config: JobConfig, runner_name: str | None = None) -> dict:
    """
    Execute a scrape job using configuration from the API.

    Args:
        job_config: Job configuration received from the coordinator
        runner_name: Optional identifier for this runner

    Returns:
        Dictionary with results to send back to the callback
    """
    job_id = job_config.job_id
    emitter = create_emitter(job_id)
    parser = ScraperConfigParser()
    collector = ResultCollector(test_mode=job_config.test_mode)

    results = {
        "skus_processed": 0,
        "scrapers_run": [],
        "data": {},
    }

    logger.info(f"[Runner] Starting job {job_id}")
    logger.info(f"[Runner] SKUs: {len(job_config.skus)}, Scrapers: {len(job_config.scrapers)}")
    logger.info(f"[Runner] Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}")

    configs = []
    for scraper_cfg in job_config.scrapers:
        try:
            config_dict = {
                "name": scraper_cfg.name,
                "base_url": scraper_cfg.base_url,
                "search_url_template": scraper_cfg.search_url_template,
                "selectors": scraper_cfg.selectors or {},
                "options": scraper_cfg.options or {},
                "test_skus": scraper_cfg.test_skus or [],
            }

            if scraper_cfg.options and "_credentials" in scraper_cfg.options:
                config_dict["_credentials"] = scraper_cfg.options["_credentials"]

            config = parser.load_from_dict(config_dict)
            configs.append(config)
            logger.info(f"[Runner] Loaded scraper config: {config.name}")
        except Exception as e:
            logger.error(f"[Runner] Failed to parse config for {scraper_cfg.name}: {e}")

    if not configs:
        logger.error("[Runner] No valid scraper configurations")
        return results

    skus = job_config.skus
    if not skus and job_config.test_mode:
        for config in configs:
            if hasattr(config, "test_skus") and config.test_skus:
                skus.extend(config.test_skus)
        skus = list(set(skus))
        logger.info(f"[Runner] Test mode: using {len(skus)} test SKUs from configs")

    if not skus:
        logger.warning("[Runner] No SKUs to process")
        return results

    for config in configs:
        logger.info(f"[Runner] Running scraper: {config.name}")
        results["scrapers_run"].append(config.name)

        executor = None
        try:
            executor = WorkflowExecutor(
                config,
                headless=True,
                timeout=30,
                worker_id="API",
                debug_mode=False,
                job_id=job_id,
                event_emitter=emitter,
            )

            for sku in skus:
                try:
                    result = executor.execute_workflow(
                        context={"sku": sku, "test_mode": job_config.test_mode},
                        quit_browser=False,
                    )

                    results["skus_processed"] += 1

                    if result.get("success"):
                        extracted_data = result.get("results", {})
                        has_data = any(extracted_data.get(field) for field in ["Name", "Brand", "Weight"])

                        if has_data:
                            if sku not in results["data"]:
                                results["data"][sku] = {}
                            results["data"][sku][config.name] = {
                                "price": extracted_data.get("Price"),
                                "title": extracted_data.get("Name"),
                                "description": extracted_data.get("Description"),
                                "images": extracted_data.get("Images", []),
                                "availability": extracted_data.get("Availability"),
                                "url": extracted_data.get("URL"),
                                "scraped_at": datetime.now().isoformat(),
                            }

                            collector.add_result(sku, config.name, extracted_data)

                            logger.info(f"[Runner] {config.name}/{sku}: Found data")
                        else:
                            logger.info(f"[Runner] {config.name}/{sku}: No data found")
                    else:
                        logger.warning(f"[Runner] {config.name}/{sku}: Workflow failed")

                except Exception as e:
                    logger.error(f"[Runner] {config.name}/{sku}: Error - {e}")

        except Exception as e:
            logger.error(f"[Runner] Failed to initialize {config.name}: {e}")
        finally:
            if executor and hasattr(executor, "browser") and executor.browser:
                try:
                    executor.browser.quit()
                except Exception:
                    pass

    logger.info(f"[Runner] Job complete. Processed {results['skus_processed']} SKUs")
    return results


def main():
    """CLI entry point for running a single job via the API."""
    parser = argparse.ArgumentParser(description="Run a scrape job from the API")
    parser.add_argument("--job-id", help="Job ID to execute")
    parser.add_argument("--api-url", help="API base URL (or set SCRAPER_API_URL)")
    parser.add_argument("--runner-name", default=os.environ.get("RUNNER_NAME", "unknown"))
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    args = parser.parse_args()

    # Handle version check
    if args.version:
        version_file = PROJECT_ROOT / "VERSION"
        if version_file.exists():
            print(f"BayStateScraper v{version_file.read_text().strip()}")
        else:
            print("BayStateScraper v(unknown)")
        sys.exit(0)

    if not args.job_id:
        parser.error("--job-id is required unless --version is specified")

    log_level = logging.DEBUG if args.debug else logging.INFO
    if args.debug:
        os.environ["LOG_LEVEL"] = "DEBUG"
    setup_logging(debug_mode=args.debug)

    api_url = args.api_url or os.environ.get("SCRAPER_API_URL")
    if not api_url:
        logger.error("No API URL provided. Set --api-url or SCRAPER_API_URL")
        sys.exit(1)

    client = ScraperAPIClient(api_url=api_url, runner_name=args.runner_name)

    # Configure API logging
    try:
        from utils.api_handler import ScraperAPIHandler

        api_handler = ScraperAPIHandler(client, args.job_id)

        api_handler.addFilter(NoHttpFilter())
        logging.getLogger().addHandler(api_handler)
        logger.debug("API logging enabled")
    except Exception as e:
        logger.warning(f"Failed to enable API logging: {e}")

    logger.info(f"Fetching job config for {args.job_id}...")
    client.update_status(args.job_id, "running", runner_name=args.runner_name)

    job_config = client.get_job_config(args.job_id)
    if not job_config:
        logger.error("Failed to fetch job config")
        client.submit_results(
            args.job_id,
            "failed",
            runner_name=args.runner_name,
            error_message="Failed to fetch job configuration",
        )
        sys.exit(1)

    try:
        results = run_job(job_config, runner_name=args.runner_name)
        client.submit_results(
            args.job_id,
            "completed",
            runner_name=args.runner_name,
            results=results,
        )

        import json

        print(json.dumps(results, indent=2))

    except Exception as e:
        logger.exception("Job failed with error")
        client.submit_results(
            args.job_id,
            "failed",
            runner_name=args.runner_name,
            error_message=str(e),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
