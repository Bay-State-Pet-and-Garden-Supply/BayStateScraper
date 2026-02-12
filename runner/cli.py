from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from core.api_client import ConnectionError, ScraperAPIClient
from utils.structured_logging import setup_structured_logging

from runner.chunk_mode import run_chunk_worker_mode
from runner.full_mode import run_full_mode
from runner.realtime_mode import run_realtime_mode

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a scrape job from the API")
    parser.add_argument("--job-id", help="Job ID to execute")
    parser.add_argument("--api-url", help="API base URL (or set SCRAPER_API_URL)")
    parser.add_argument("--runner-name", default=os.environ.get("RUNNER_NAME", "unknown"))
    parser.add_argument(
        "--mode",
        choices=["full", "chunk_worker", "realtime"],
        default="full",
        help="Execution mode: 'full', 'chunk_worker', or 'realtime'",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.mode in {"full", "chunk_worker"} and not args.job_id:
        parser.error("--job-id is required unless --mode realtime")

    return args


def main() -> None:
    args = parse_args()
    setup_structured_logging(debug=args.debug)

    api_url = args.api_url or os.environ.get("SCRAPER_API_URL")
    if not api_url:
        logger.error("No API URL provided. Set --api-url or SCRAPER_API_URL")
        sys.exit(1)

    client = ScraperAPIClient(api_url=api_url, runner_name=args.runner_name)

    logger.info(f"[Runner] Performing pre-flight health check against {api_url}")
    try:
        client.health_check()
    except ConnectionError as e:
        logger.error(f"[Runner] Pre-flight health check failed: {e}")
        sys.exit(1)

    if args.mode == "realtime":
        asyncio.run(run_realtime_mode(client, args.runner_name))
    elif args.mode == "chunk_worker":
        run_chunk_worker_mode(client, args.job_id, args.runner_name)
    else:
        run_full_mode(client, args.job_id, args.runner_name)
