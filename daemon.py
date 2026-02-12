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
    python daemon.py                    # Uses .env (production)
    python daemon.py --env dev          # Uses .env.development (local dev)
    ENVIRONMENT=dev python daemon.py    # Same as above

Environment Variables:
    SCRAPER_API_URL: Base URL for BayStateApp API (required)
    SCRAPER_API_KEY: API key for authentication (required)
    RUNNER_NAME: Identifier for this runner (defaults to hostname)
    POLL_INTERVAL: Seconds between polls when idle (default: 30)
    MAX_JOBS_BEFORE_RESTART: Recycle after N jobs to prevent leaks (default: 100)
    ENVIRONMENT: Set to 'dev' to use .env.development instead of .env
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import signal
import sys
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

parser = argparse.ArgumentParser(description="Bay State Scraper Daemon")
parser.add_argument(
    "--env",
    choices=["dev", "prod"],
    default=os.environ.get("ENVIRONMENT", "prod"),
    help="Environment to run in (dev=localhost, prod=production). Defaults to ENVIRONMENT env var or 'prod'",
)
parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable debug logging",
)
args, remaining_argv = parser.parse_known_args()

if args.env == "dev":
    env_file = PROJECT_ROOT / ".env.development"
    if not env_file.exists():
        print(f"Warning: {env_file} not found, falling back to .env")
        env_file = PROJECT_ROOT / ".env"
else:
    env_file = PROJECT_ROOT / ".env"

if env_file.exists():
    load_dotenv(env_file, override=True)


from core.api_client import ClaimedChunk, ScraperAPIClient, JobConfig
from core.realtime_manager import RealtimeManager
from utils.logger import setup_logging


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


def _create_log_entry(level: str, message: str) -> dict[str, str]:
    return {
        "level": level,
        "message": message,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def run_job(
    job_config: JobConfig,
    client: ScraperAPIClient,
    log_buffer: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute a scrape job using the existing runner logic.

    This imports and calls the run_job function from runner.py,
    but fetches credentials from the coordinator instead of local storage.
    """
    from runner import run_job

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

    return run_job(job_config, runner_name=client.runner_name, log_buffer=log_buffer)


def run_claimed_chunk(
    chunk: ClaimedChunk,
    client: ScraperAPIClient,
    log_buffer: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    job_config = client.get_job_config(chunk.job_id)
    if not job_config:
        raise RuntimeError(f"Failed to fetch job config for chunk job {chunk.job_id}")

    job_config.skus = chunk.skus
    job_config.test_mode = chunk.test_mode
    job_config.max_workers = chunk.max_workers

    if chunk.scrapers:
        job_config.scrapers = [s for s in job_config.scrapers if s.name in chunk.scrapers]

    return run_job(job_config, client, log_buffer)


def needs_credentials(scraper_name: str) -> bool:
    """Check if a scraper requires login credentials."""
    # Known scrapers that require authentication
    LOGIN_SCRAPERS = {"petfoodex", "phillips", "orgill", "shopsite"}
    return scraper_name.lower() in LOGIN_SCRAPERS


async def main_async():
    """Main async daemon loop."""
    global _shutdown_requested

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
    logger.info(f"Environment: {args.env.upper()}")
    logger.info(f"Runner Name: {client.runner_name}")
    logger.info(f"API URL: {client.api_url}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Poll Interval: {POLL_INTERVAL}s")
    logger.info(f"Max Jobs Before Restart: {MAX_JOBS_BEFORE_RESTART}")
    logger.info("=" * 60)

    logger.info("Daemon API handler disabled; per-job log batches enabled")

    rm = None
    try:
        supabase_config = client.get_supabase_config()
        if supabase_config:
            # Convert HTTP URL to WebSocket URL format
            supabase_url = supabase_config["supabase_url"]
            if supabase_url.startswith("https://"):
                ws_url = supabase_url.replace("https://", "wss://") + "/realtime/v1"
            elif supabase_url.startswith("http://"):
                ws_url = supabase_url.replace("http://", "ws://") + "/realtime/v1"
            else:
                ws_url = supabase_url

            logger.info(f"[Daemon] Connecting to Realtime at {ws_url}")
            rm = RealtimeManager(ws_url, supabase_config["supabase_realtime_key"], client.runner_name)
            connected = await rm.connect()
            if connected:
                await rm.enable_presence()
                await rm.enable_broadcast()
                logger.info("[Daemon] Persistent Realtime presence enabled")
    except Exception as e:
        logger.warning(f"[Daemon] Failed to initialize Realtime presence: {e}")

    chunks_completed = 0
    last_heartbeat = 0

    logger.info("[Daemon] Entering main polling loop")

    while not _shutdown_requested:
        try:
            if chunks_completed >= MAX_JOBS_BEFORE_RESTART:
                logger.info(f"Completed {chunks_completed} chunks. Exiting for container restart (memory hygiene).")
                break

            logger.info("[Daemon] Claiming next work unit...")
            chunk = await asyncio.to_thread(client.claim_chunk, runner_name=client.runner_name)
            logger.info(f"[Daemon] Claim result: {chunk}")

            if chunk:
                logger.info(f"[Chunk {chunk.chunk_id}] Claimed - job={chunk.job_id}, skus={len(chunk.skus)}")

                try:
                    await asyncio.to_thread(client.heartbeat, current_job_id=chunk.job_id, lease_token=chunk.lease_token, status="busy")
                    if rm and rm.is_connected:
                        await rm.broadcast_job_progress(chunk.job_id, "started", 0, "Chunk processing started")

                    chunk_logs: list[dict[str, Any]] = []
                    chunk_logs.append(_create_log_entry("info", f"Daemon claimed chunk {chunk.chunk_id} for job {chunk.job_id}"))
                    start_time = time.time()
                    results = await asyncio.to_thread(run_claimed_chunk, chunk, client, chunk_logs)
                    elapsed = time.time() - start_time
                    chunk_logs.append(_create_log_entry("info", f"Daemon completed chunk in {elapsed:.1f}s"))

                    chunk_results = {
                        "skus_processed": results.get("skus_processed", 0),
                        "skus_successful": len(results.get("data", {})),
                        "skus_failed": results.get("skus_processed", 0) - len(results.get("data", {})),
                        "data": results.get("data", {}),
                    }

                    await asyncio.to_thread(
                        client.submit_chunk_results,
                        chunk.chunk_id,
                        "completed",
                        results=chunk_results,
                    )

                    if chunk_logs:
                        try:
                            await asyncio.to_thread(client.post_logs, chunk.job_id, chunk_logs)
                        except Exception as log_error:
                            logger.warning(f"[Chunk {chunk.chunk_id}] Failed to send logs: {log_error}")

                    chunks_completed += 1
                    logger.info(f"[Chunk {chunk.chunk_id}] Completed in {elapsed:.1f}s - {results.get('skus_processed', 0)} SKUs processed")

                except Exception as e:
                    failure_logs = [
                        _create_log_entry("error", f"Daemon failed chunk {chunk.chunk_id}: {type(e).__name__} - {e}"),
                    ]
                    logger.exception(f"[Chunk {chunk.chunk_id}] Failed with error")
                    await asyncio.to_thread(
                        client.submit_chunk_results,
                        chunk.chunk_id,
                        "failed",
                        error_message=str(e),
                    )
                    try:
                        await asyncio.to_thread(client.post_logs, chunk.job_id, failure_logs)
                    except Exception as log_error:
                        logger.warning(f"[Chunk {chunk.chunk_id}] Failed to send error logs: {log_error}")

            else:
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    await asyncio.to_thread(client.heartbeat, status="idle")
                    last_heartbeat = now
                    logger.debug("Heartbeat sent")

                await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.error(f"Daemon loop error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    if rm:
        await rm.disconnect()

    logger.info("=" * 60)
    logger.info(f"Daemon shutting down. Chunks completed: {chunks_completed}")
    logger.info("=" * 60)


def main():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
