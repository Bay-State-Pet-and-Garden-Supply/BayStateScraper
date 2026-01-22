#!/usr/bin/env python3
"""
Bay State Scraper - Long-Running Daemon

A persistent polling daemon that continuously checks for work from the coordinator.
Designed to run inside a Docker container with `restart: unless-stopped`.

Key behaviors:
- Polls coordinator every POLL_INTERVAL seconds for new jobs
- Sends heartbeat when idle so coordinator knows runner is alive
- Fetches credentials on-demand from coordinator (never stored locally)
- Recycles browser after MAX_JOBS_BEFORE_RESTART to prevent memory leaks
- Graceful shutdown on SIGTERM/SIGINT

Usage:
    python daemon.py

Environment Variables:
    SCRAPER_API_URL: Base URL for BayStateApp API (required)
    SCRAPER_API_KEY: API key for authentication (required)
    RUNNER_NAME: Identifier for this runner (defaults to hostname)
    POLL_INTERVAL: Seconds between polls when idle (default: 30)
    MAX_JOBS_BEFORE_RESTART: Recycle after N jobs to prevent leaks (default: 100)
"""

from __future__ import annotations

import logging
import os
import platform
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.api_client import ScraperAPIClient, JobConfig
from utils.logger import NoHttpFilter, setup_logging


# Configuration
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
MAX_JOBS_BEFORE_RESTART = int(os.environ.get("MAX_JOBS_BEFORE_RESTART", "100"))
HEARTBEAT_INTERVAL = 60  # Send heartbeat every 60 seconds when idle

# Setup logging
setup_logging(debug_mode=False)
logger = logging.getLogger("daemon")

# Global shutdown flag
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handle graceful shutdown on SIGTERM/SIGINT."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, initiating graceful shutdown...")
    _shutdown_requested = True


def run_job(job_config: JobConfig, client: ScraperAPIClient) -> dict:
    """
    Execute a scrape job using the existing runner logic.

    This imports and calls the run_job function from runner.py,
    but fetches credentials from the coordinator instead of local storage.
    """
    from runner import run_job as execute_job

    # Fetch credentials for any scrapers that require login
    for scraper in job_config.scrapers:
        if needs_credentials(scraper.name):
            creds = client.get_credentials(scraper.name)
            if creds:
                # Inject credentials into scraper options
                if scraper.options is None:
                    scraper.options = {}
                scraper.options["_credentials"] = creds
                logger.debug(f"Injected credentials for {scraper.name}")

    return execute_job(job_config, runner_name=client.runner_name)


def needs_credentials(scraper_name: str) -> bool:
    """Check if a scraper requires login credentials."""
    # Known scrapers that require authentication
    LOGIN_SCRAPERS = {"petfoodex", "phillips", "orgill", "shopsite"}
    return scraper_name.lower() in LOGIN_SCRAPERS


def main():
    """Main daemon loop."""
    global _shutdown_requested

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Initialize API client
    client = ScraperAPIClient()

    # Read version
    version = "unknown"
    version_file = PROJECT_ROOT / "VERSION"
    if version_file.exists():
        version = version_file.read_text().strip()

    if not client.api_url or not client.api_key:
        logger.error("Missing SCRAPER_API_URL or SCRAPER_API_KEY. Cannot start daemon.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"Bay State Scraper Daemon Starting (v{version})")
    logger.info("=" * 60)
    logger.info(f"Runner Name: {client.runner_name}")
    logger.info(f"API URL: {client.api_url}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Poll Interval: {POLL_INTERVAL}s")
    logger.info(f"Max Jobs Before Restart: {MAX_JOBS_BEFORE_RESTART}")
    logger.info("=" * 60)

    try:
        from utils.api_handler import ScraperAPIHandler

        api_handler = ScraperAPIHandler(client, job_id="daemon")
        api_handler.addFilter(NoHttpFilter())
        logging.getLogger().addHandler(api_handler)
        logger.debug("API logging enabled")
    except Exception as e:
        logger.warning(f"Failed to enable API logging: {e}")

    jobs_completed = 0
    last_heartbeat = 0

    # Main polling loop
    while not _shutdown_requested:
        try:
            # Check if we should restart for memory hygiene
            if jobs_completed >= MAX_JOBS_BEFORE_RESTART:
                logger.info(f"Completed {jobs_completed} jobs. Exiting for container restart (memory hygiene).")
                break

            # Poll for work
            job = client.poll_for_work()

            if job:
                logger.info(f"[Job {job.job_id}] Claimed - {len(job.skus)} SKUs, {len(job.scrapers)} scrapers")

                try:
                    # Update status to running
                    client.update_status(job.job_id, "running")

                    # Execute the job
                    start_time = time.time()
                    results = run_job(job, client)
                    elapsed = time.time() - start_time

                    # Submit results
                    client.submit_results(
                        job.job_id,
                        "completed",
                        results=results,
                    )

                    jobs_completed += 1
                    logger.info(f"[Job {job.job_id}] Completed in {elapsed:.1f}s - {results.get('skus_processed', 0)} SKUs processed")

                except Exception as e:
                    logger.exception(f"[Job {job.job_id}] Failed with error")
                    client.submit_results(
                        job.job_id,
                        "failed",
                        error_message=str(e),
                    )

            else:
                # No work available - send heartbeat if interval elapsed
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    client.heartbeat()
                    last_heartbeat = now
                    logger.debug("Heartbeat sent")

                # Sleep before next poll
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            break

        except Exception as e:
            logger.error(f"Daemon loop error: {e}")
            # Sleep before retry to avoid tight error loop
            time.sleep(POLL_INTERVAL)

    # Graceful shutdown
    logger.info("=" * 60)
    logger.info(f"Daemon shutting down. Jobs completed: {jobs_completed}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
