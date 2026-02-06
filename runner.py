"""
API-Driven Job Runner for GitHub Actions.

This module provides the entry point for running scrape jobs triggered by the
BayStateApp coordinator API. Unlike the legacy run_scraping() function, this
module fetches configuration from the API and submits results back via HTTP.

Usage:
    python -m runner --job-id <uuid>

Environment Variables:
    SCRAPER_API_URL: Base URL for BayStateApp API
    SCRAPER_WEBHOOK_SECRET: Shared secret for HMAC authentication
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Any

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.api_client import ScraperAPIClient, JobConfig
from core.events import create_emitter
from scrapers.parser import ScraperConfigParser
from scrapers.executor.workflow_executor import WorkflowExecutor
from scrapers.result_collector import ResultCollector
from utils.logger import NoHttpFilter, setup_logging

logger = logging.getLogger(__name__)


# =============================================================================
# Log Buffering for API Submission
# =============================================================================


def create_log_entry(level: str, message: str) -> dict[str, Any]:
    """
    Create a log entry in the format expected by the API.

    Args:
        level: Log level (debug, info, warning, error, critical)
        message: Log message text

    Returns:
        Dictionary with keys: level, message, timestamp
    """
    return {
        "level": level,
        "message": message,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


class ConfigurationError(Exception):
    """Raised when configuration parsing fails."""

    pass


def run_job(job_config: JobConfig, runner_name: str | None = None, log_buffer: list[dict] | None = None) -> dict:
    """
    Execute a scrape job using configuration from the API.

    Args:
        job_config: Job configuration received from the coordinator
        runner_name: Optional identifier for this runner
        log_buffer: Optional list to accumulate logs for API submission

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

    # Initialize log buffer if not provided
    if log_buffer is None:
        log_buffer = []

    # Add job start log
    log_buffer.append(create_log_entry("info", f"Job {job_id} started"))
    log_buffer.append(create_log_entry("info", f"Processing {len(job_config.skus)} SKUs with {len(job_config.scrapers)} scrapers"))
    log_buffer.append(create_log_entry("info", f"Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}"))

    logger.info(f"[Runner] Starting job {job_id}")
    logger.info(f"[Runner] SKUs: {len(job_config.skus)}, Scrapers: {len(job_config.scrapers)}")
    logger.info(f"[Runner] Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}")

    # Parse scraper configs into internal format
    configs = []
    config_errors = []
    for scraper_cfg in job_config.scrapers:
        try:
            # Convert API config to internal format
            # Note: Use proper None checks to preserve empty lists
            config_dict = {
                "name": scraper_cfg.name,
                "base_url": scraper_cfg.base_url,
                "search_url_template": scraper_cfg.search_url_template,
                "selectors": scraper_cfg.selectors if scraper_cfg.selectors is not None else {},
                "options": scraper_cfg.options if scraper_cfg.options is not None else {},
                "test_skus": scraper_cfg.test_skus if scraper_cfg.test_skus is not None else [],
            }
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

    # Determine SKUs to process
    skus = job_config.skus
    if not skus and job_config.test_mode:
        # In test mode without SKUs, use each scraper's test_skus
        for config in configs:
            if hasattr(config, "test_skus") and config.test_skus:
                skus.extend(config.test_skus)
        skus = list(set(skus))  # Deduplicate
        log_buffer.append(create_log_entry("info", f"Test mode: using {len(skus)} test SKUs from configs"))
        logger.info(f"[Runner] Test mode: using {len(skus)} test SKUs from configs")

    if not skus:
        log_buffer.append(create_log_entry("warning", "No SKUs to process"))
        logger.warning("[Runner] No SKUs to process")
        return results

    # Run scraping for each config
    for config in configs:
        log_buffer.append(create_log_entry("info", f"Starting scraper: {config.name}"))
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
                            # Store result by SKU
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

                            # Also add to collector for JSON output
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
                    log_buffer.append(create_log_entry("error", f"{config.name}/{sku}: {type(e).__name__} - {e}"))
                    logger.error(f"[Runner] {config.name}/{sku}: Error - {e}")

        except Exception as e:
            log_buffer.append(create_log_entry("error", f"Failed to initialize {config.name}: {e}"))
            logger.error(f"[Runner] Failed to initialize {config.name}: {e}")
        finally:
            if executor and hasattr(executor, "browser") and executor.browser:
                try:
                    executor.browser.quit()
                except Exception:
                    pass

    log_buffer.append(create_log_entry("info", f"Job complete. Processed {results['skus_processed']} SKUs"))
    logger.info(f"[Runner] Job complete. Processed {results['skus_processed']} SKUs")
    return results


def main():
    """CLI entry point for running a job via the API."""
    parser = argparse.ArgumentParser(description="Run a scrape job from the API")
    parser.add_argument("--job-id", required=True, help="Job ID to execute")
    parser.add_argument("--api-url", help="API base URL (or set SCRAPER_API_URL)")
    parser.add_argument("--runner-name", default=os.environ.get("RUNNER_NAME", "unknown"))
    parser.add_argument(
        "--mode",
        choices=["full", "chunk_worker"],
        default="full",
        help="Execution mode: 'full' (legacy) or 'chunk_worker' (claim chunks)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    if args.debug:
        os.environ["LOG_LEVEL"] = "DEBUG"
    setup_logging(debug_mode=args.debug)

    # Initialize API client
    api_url = args.api_url or os.environ.get("SCRAPER_API_URL")
    if not api_url:
        logger.error("No API URL provided. Set --api-url or SCRAPER_API_URL")
        sys.exit(1)

    client = ScraperAPIClient(api_url=api_url, runner_name=args.runner_name)

    if args.mode == "chunk_worker":
        run_chunk_worker_mode(client, args.job_id, args.runner_name)
    else:
        run_full_mode(client, args.job_id, args.runner_name)


def run_full_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    """Legacy mode: process all SKUs in a single job."""
    log_buffer: list[dict] = []
    log_buffer.append(create_log_entry("info", f"Full mode started for job {job_id}, runner: {runner_name}"))

    logger.info(f"[Full Mode] Fetching job config for {job_id}...")
    log_buffer.append(create_log_entry("info", f"Fetching job config for {job_id}"))
    client.update_status(job_id, "running", runner_name=runner_name)

    job_config = client.get_job_config(job_id)
    if not job_config:
        log_buffer.append(create_log_entry("error", "Failed to fetch job config"))
        logger.error("Failed to fetch job config")
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            error_message="Failed to fetch job configuration",
        )
        client.post_logs(job_id, log_buffer)
        sys.exit(1)

    try:
        results = run_job(job_config, runner_name=runner_name, log_buffer=log_buffer)
        log_buffer.append(create_log_entry("info", f"Job completed successfully, {results.get('skus_processed', 0)} SKUs processed"))
        client.submit_results(
            job_id,
            "completed",
            runner_name=runner_name,
            results=results,
        )
        client.post_logs(job_id, log_buffer)

        import json

        print(json.dumps(results, indent=2))

    except Exception as e:
        log_buffer.append(create_log_entry("error", f"Job failed: {type(e).__name__} - {e}"))
        logger.exception("Job failed with error")
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            error_message=str(e),
        )
        client.post_logs(job_id, log_buffer)
        sys.exit(1)


def run_chunk_worker_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    """Chunk worker mode: claim and process chunks until none remain."""
    logger.info(f"[Chunk Worker] Starting for job {job_id}")

    chunks_processed = 0
    total_skus_processed = 0
    total_successful = 0
    total_failed = 0

    while True:
        chunk = client.claim_chunk(job_id, runner_name)

        if not chunk:
            logger.info(f"[Chunk Worker] No more chunks. Processed {chunks_processed} chunks, {total_skus_processed} SKUs")
            break

        chunk_id = chunk["chunk_id"]
        chunk_index = chunk["chunk_index"]
        skus = chunk.get("skus", [])
        scrapers_filter = chunk.get("scrapers", [])

        logger.info(f"[Chunk Worker] Processing chunk {chunk_index} with {len(skus)} SKUs")

        try:
            job_config = client.get_job_config(job_id)
            if not job_config:
                raise RuntimeError("Failed to fetch job config for chunk")

            job_config.skus = skus
            if scrapers_filter:
                job_config.scrapers = [s for s in job_config.scrapers if s.name in scrapers_filter]

            results = run_job(job_config, runner_name=runner_name)

            chunk_results = {
                "skus_processed": results.get("skus_processed", 0),
                "skus_successful": len(results.get("data", {})),
                "skus_failed": results.get("skus_processed", 0) - len(results.get("data", {})),
                "data": results.get("data", {}),
            }

            client.submit_chunk_results(chunk_id, "completed", results=chunk_results)

            chunks_processed += 1
            total_skus_processed += chunk_results["skus_processed"]
            total_successful += chunk_results["skus_successful"]
            total_failed += chunk_results["skus_failed"]

            logger.info(f"[Chunk Worker] Completed chunk {chunk_index}: {chunk_results['skus_successful']}/{chunk_results['skus_processed']} successful")

        except Exception as e:
            logger.exception(f"[Chunk Worker] Chunk {chunk_index} failed")
            client.submit_chunk_results(chunk_id, "failed", error_message=str(e))
            chunks_processed += 1

    logger.info(f"[Chunk Worker] Finished. Total: {chunks_processed} chunks, {total_successful}/{total_skus_processed} successful")


if __name__ == "__main__":
    main()
