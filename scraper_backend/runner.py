"""
API-Driven Job Runner for GitHub Actions.

This module provides the entry point for running scrape jobs triggered by the
BayStateApp coordinator API. Unlike the legacy run_scraping() function, this
module fetches configuration from the API and submits results back via HTTP.

Usage:
    python -m scraper_backend.runner --job-id <uuid>

Environment Variables:
    SCRAPER_API_URL: Base URL for BayStateApp API
    SCRAPER_WEBHOOK_SECRET: Shared secret for HMAC authentication
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from logging import LogRecord
from typing import Any

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scraper_backend.core.api_client import ScraperAPIClient, JobConfig, ConnectionError
from scraper_backend.core.config_fetcher import (
    fetch_and_validate_config,
    ConfigFetchError,
    ConfigValidationError,
)
from scraper_backend.core.events import create_emitter
from scraper_backend.core.realtime_manager import RealtimeManager
from scraper_backend.scrapers.parser import ScraperConfigParser
from scraper_backend.scrapers.executor.workflow_executor import WorkflowExecutor
from scraper_backend.scrapers.result_collector import ResultCollector

logger = logging.getLogger(__name__)

# =============================================================================
# Structured Logging Classes
# =============================================================================


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that redacts sensitive data from log records.

    Sensitive patterns include:
    - API keys (bsr_*, X-API-Key headers)
    - Passwords
    - Tokens
    - Authorization headers
    """

    # Patterns that match sensitive data
    SENSITIVE_PATTERNS = [
        (r"bsr_[a-zA-Z0-9]{32,}", "[API_KEY_REDACTED]"),
        (r'X-API-Key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_-]+', "[API_KEY_REDACTED]"),
        (r'["\']?password["\']?\s*[:=]\s*["\']?[^\s"\']+', "[PASSWORD_REDACTED]"),
        (r"Bearer\s+[a-zA-Z0-9_\-\.]+", "[TOKEN_REDACTED]"),
        (r'Authorization["\']?\s*[:=]\s*["\']?[^\s"\']+', "[AUTH_REDACTED]"),
    ]

    def filter(self, record: LogRecord) -> bool:
        """Redact sensitive data from log message and extra fields."""
        # Redact from message
        record.msg = self._redact(str(record.msg))

        # Redact from args (formatted message arguments)
        if record.args:
            record.args = tuple(self._redact(str(arg)) if isinstance(arg, (str, bytes)) else arg for arg in record.args)

        # Redact from extra fields that will be included in JSON
        if hasattr(record, "job_id"):
            record.job_id = self._redact(str(record.job_id)) if record.job_id else None
        if hasattr(record, "scraper_name"):
            record.scraper_name = self._redact(str(record.scraper_name)) if record.scraper_name else None
        if hasattr(record, "trace_id"):
            record.trace_id = self._redact(str(record.trace_id)) if record.trace_id else None

        return True

    def _redact(self, text: str) -> str:
        """Apply all redaction patterns to text."""
        result = text
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured log output.

    Outputs logs as JSON objects with consistent fields:
    - timestamp: ISO format timestamp
    - level: Log level (INFO, ERROR, etc.)
    - logger: Logger name
    - message: Log message
    - job_id: Job context (if available)
    - scraper_name: Scraper context (if available)
    - trace_id: Trace ID for debugging (if available)
    - module: Module name
    - function: Function name
    - line: Line number
    """

    def format(self, record: LogRecord) -> str:
        """Format log record as JSON string."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context fields if present
        if hasattr(record, "job_id") and record.job_id:
            log_data["job_id"] = record.job_id
        if hasattr(record, "scraper_name") and record.scraper_name:
            log_data["scraper_name"] = record.scraper_name
        if hasattr(record, "trace_id") and record.trace_id:
            log_data["trace_id"] = record.trace_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "message",
                "job_id",
                "scraper_name",
                "trace_id",
            ):
                try:
                    # Only include JSON-serializable values
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, ValueError):
                    pass

        return json.dumps(log_data)


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    return str(uuid.uuid4())[:8]


def setup_structured_logging(debug: bool = False) -> None:
    """
    Configure structured logging with JSON output and sensitive data redaction.

    Args:
        debug: Enable debug logging level
    """
    log_level = logging.DEBUG if debug else logging.INFO

    # Create JSON formatter
    json_formatter = JSONFormatter()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(json_formatter)
    handler.addFilter(SensitiveDataFilter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Also configure our module logger
    module_logger = logging.getLogger(__name__)
    module_logger.setLevel(log_level)


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
    job_trace_id = generate_trace_id()
    emitter = create_emitter(job_id)
    parser = ScraperConfigParser()
    collector = ResultCollector(test_mode=job_config.test_mode)

    results = {
        "skus_processed": 0,
        "scrapers_run": [],
        "data": {},
    }

    logger.info(
        f"[Runner] Starting job {job_id}",
        extra={
            "job_id": job_id,
            "trace_id": job_trace_id,
            "sku_count": len(job_config.skus),
            "scraper_count": len(job_config.scrapers),
            "test_mode": job_config.test_mode,
            "max_workers": job_config.max_workers,
        },
    )
    logger.info(f"[Runner] SKUs: {len(job_config.skus)}, Scrapers: {len(job_config.scrapers)}", extra={"job_id": job_id, "trace_id": job_trace_id})
    logger.info(f"[Runner] Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}", extra={"job_id": job_id, "trace_id": job_trace_id})

    # Parse scraper configs into internal format
    configs = []
    for scraper_cfg in job_config.scrapers:
        try:
            # Convert API config to internal format
            config_dict = {
                "name": scraper_cfg.name,
                "base_url": scraper_cfg.base_url,
                "search_url_template": scraper_cfg.search_url_template,
                "selectors": scraper_cfg.selectors or {},
                "options": scraper_cfg.options or {},
                "test_skus": scraper_cfg.test_skus or [],
            }
            config = parser.load_from_dict(config_dict)
            configs.append(config)
            logger.info(f"[Runner] Loaded scraper config: {config.name}", extra={"job_id": job_id, "trace_id": job_trace_id, "scraper_name": config.name})
        except Exception as e:
            logger.error(
                f"[Runner] Failed to parse config for {scraper_cfg.name}: {e}",
                extra={
                    "job_id": job_id,
                    "trace_id": job_trace_id,
                    "scraper_name": scraper_cfg.name,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    if not configs:
        logger.error(
            "[Runner] No valid scraper configurations",
            extra={
                "job_id": job_id,
                "trace_id": job_trace_id,
                "error_type": "ConfigurationError",
                "scraper_count": len(job_config.scrapers),
            },
        )
        return results

    # Determine SKUs to process
    skus = job_config.skus
    if not skus and job_config.test_mode:
        # In test mode without SKUs, use each scraper's test_skus
        for config in configs:
            if hasattr(config, "test_skus") and config.test_skus:
                skus.extend(config.test_skus)
        skus = list(set(skus))  # Deduplicate
        logger.info(f"[Runner] Test mode: using {len(skus)} test SKUs from configs", extra={"job_id": job_id, "trace_id": job_trace_id, "sku_count": len(skus)})

    if not skus:
        logger.warning("[Runner] No SKUs to process", extra={"job_id": job_id, "trace_id": job_trace_id})
        return results

    # Run scraping for each config
    for config in configs:
        scraper_trace_id = generate_trace_id()
        logger.info(
            f"[Runner] Running scraper: {config.name}",
            extra={
                "job_id": job_id,
                "trace_id": job_trace_id,
                "scraper_name": config.name,
                "scraper_trace_id": scraper_trace_id,
            },
        )
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

                            logger.info(
                                f"[Runner] {config.name}/{sku}: Found data",
                                extra={
                                    "job_id": job_id,
                                    "trace_id": job_trace_id,
                                    "scraper_name": config.name,
                                    "scraper_trace_id": scraper_trace_id,
                                    "sku": sku,
                                    "status": "success",
                                },
                            )
                        else:
                            logger.info(
                                f"[Runner] {config.name}/{sku}: No data found",
                                extra={
                                    "job_id": job_id,
                                    "trace_id": job_trace_id,
                                    "scraper_name": config.name,
                                    "scraper_trace_id": scraper_trace_id,
                                    "sku": sku,
                                    "status": "no_data",
                                },
                            )
                    else:
                        logger.warning(
                            f"[Runner] {config.name}/{sku}: Workflow failed",
                            extra={
                                "job_id": job_id,
                                "trace_id": job_trace_id,
                                "scraper_name": config.name,
                                "scraper_trace_id": scraper_trace_id,
                                "sku": sku,
                                "status": "workflow_failed",
                            },
                        )

                except Exception as e:
                    logger.error(
                        f"[Runner] {config.name}/{sku}: Error - {e}",
                        extra={
                            "job_id": job_id,
                            "trace_id": job_trace_id,
                            "scraper_name": config.name,
                            "scraper_trace_id": scraper_trace_id,
                            "sku": sku,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        },
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(
                f"[Runner] Failed to initialize {config.name}: {e}",
                extra={
                    "job_id": job_id,
                    "trace_id": job_trace_id,
                    "scraper_name": config.name,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
                exc_info=True,
            )
        finally:
            if executor and hasattr(executor, "browser") and executor.browser:
                try:
                    executor.browser.quit()
                except Exception:
                    pass

    logger.info(
        f"[Runner] Job complete. Processed {results['skus_processed']} SKUs",
        extra={
            "job_id": job_id,
            "trace_id": job_trace_id,
            "skus_processed": results["skus_processed"],
            "scrapers_run": results["scrapers_run"],
        },
    )
    return results


def main():
    """CLI entry point for running a job via the API."""
    parser = argparse.ArgumentParser(description="Run a scrape job from the API")
    parser.add_argument("--job-id", required=True, help="Job ID to execute")
    parser.add_argument("--api-url", help="API base URL (or set SCRAPER_API_URL)")
    parser.add_argument("--runner-name", default=os.environ.get("RUNNER_NAME", "unknown"))
    parser.add_argument(
        "--mode",
        choices=["full", "chunk_worker", "realtime"],
        default="full",
        help="Execution mode: 'full' (legacy), 'chunk_worker' (claim chunks), or 'realtime' (listen for jobs via Supabase Realtime)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure structured logging
    setup_structured_logging(debug=args.debug)

    # Initialize API client
    api_url = args.api_url or os.environ.get("SCRAPER_API_URL")
    if not api_url:
        logger.error("No API URL provided. Set --api-url or SCRAPER_API_URL")
        sys.exit(1)

    client = ScraperAPIClient(api_url=api_url, runner_name=args.runner_name)

    # Pre-flight health check - fail fast if API is unreachable
    logger.info(f"[Runner] Performing pre-flight health check against {api_url}")
    try:
        healthy = client.health_check()
        if healthy:
            logger.info("[Runner] API connection verified - ready to execute jobs")
    except ConnectionError as e:
        logger.error(f"[Runner] Pre-flight health check failed: {e}")
        logger.error("[Runner] Cannot proceed - API is unreachable. Check SCRAPER_API_URL and network connectivity.")
        sys.exit(1)

    if args.mode == "realtime":
        asyncio.run(run_realtime_mode(client, args.runner_name))
    elif args.mode == "chunk_worker":
        run_chunk_worker_mode(client, args.job_id, args.runner_name)
    else:
        run_full_mode(client, args.job_id, args.runner_name)


def run_full_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    """Legacy mode: process all SKUs in a single job."""
    mode_trace_id = generate_trace_id()
    logger.info(f"[Full Mode] Starting job {job_id}", extra={"job_id": job_id, "trace_id": mode_trace_id, "runner_name": runner_name})
    logger.info(f"[Full Mode] Runner: {runner_name}, API: {client.api_url}", extra={"job_id": job_id, "trace_id": mode_trace_id, "runner_name": runner_name})
    logger.info(f"[Full Mode] Fetching job config for {job_id}...", extra={"job_id": job_id, "trace_id": mode_trace_id})
    client.update_status(job_id, "running", runner_name=runner_name)

    job_config = client.get_job_config(job_id)
    if not job_config:
        logger.error(
            "Failed to fetch job config",
            extra={
                "job_id": job_id,
                "trace_id": mode_trace_id,
                "runner_name": runner_name,
                "error_type": "ConfigFetchError",
            },
        )
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            error_message="Failed to fetch job configuration",
        )
        sys.exit(1)

    try:
        results = run_job(job_config, runner_name=runner_name)
        client.submit_results(
            job_id,
            "completed",
            runner_name=runner_name,
            lease_token=job_config.lease_token,
            results=results,
        )

        import json

        print(json.dumps(results, indent=2))

    except ConfigValidationError as e:
        logger.error(
            f"[Full Mode] Config validation failed: {e.message} (slug={e.config_slug}, schema_version={e.schema_version})",
            extra={
                "job_id": job_id,
                "trace_id": mode_trace_id,
                "runner_name": runner_name,
                "error_type": "ConfigValidationError",
                "config_slug": e.config_slug,
                "schema_version": e.schema_version,
            },
        )
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            lease_token=job_config.lease_token,
            error_message=f"Config validation failed for {e.config_slug}: {e.message}",
        )
        sys.exit(1)
    except ConfigFetchError as e:
        logger.error(
            f"[Full Mode] Config fetch failed: {e} (slug={getattr(e, 'config_slug', None)})",
            extra={
                "job_id": job_id,
                "trace_id": mode_trace_id,
                "runner_name": runner_name,
                "error_type": "ConfigFetchError",
                "config_slug": getattr(e, "config_slug", None),
            },
        )
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            lease_token=job_config.lease_token,
            error_message=f"Config fetch failed: {e}",
        )
        sys.exit(1)
    except Exception as e:
        logger.exception(
            "Job failed with error",
            extra={
                "job_id": job_id,
                "trace_id": mode_trace_id,
                "runner_name": runner_name,
                "error_type": type(e).__name__,
            },
        )
        client.submit_results(
            job_id,
            "failed",
            runner_name=runner_name,
            lease_token=job_config.lease_token,
            error_message=str(e),
        )
        sys.exit(1)


def run_chunk_worker_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    """Chunk worker mode: claim and process chunks until none remain."""
    chunk_trace_id = generate_trace_id()
    logger.info(f"[Chunk Worker] Starting for job {job_id}", extra={"job_id": job_id, "trace_id": chunk_trace_id, "runner_name": runner_name})

    chunks_processed = 0
    total_skus_processed = 0
    total_successful = 0
    total_failed = 0

    while True:
        chunk = client.claim_chunk(job_id, runner_name)

        if not chunk:
            logger.info(
                f"[Chunk Worker] No more chunks. Processed {chunks_processed} chunks, {total_skus_processed} SKUs",
                extra={
                    "job_id": job_id,
                    "trace_id": chunk_trace_id,
                    "chunks_processed": chunks_processed,
                    "total_skus_processed": total_skus_processed,
                },
            )
            break

        chunk_id = chunk["chunk_id"]
        chunk_index = chunk["chunk_index"]
        skus = chunk.get("skus", [])
        scrapers_filter = chunk.get("scrapers", [])
        chunk_worker_trace_id = generate_trace_id()

        logger.info(
            f"[Chunk Worker] Processing chunk {chunk_index} with {len(skus)} SKUs",
            extra={
                "job_id": job_id,
                "trace_id": chunk_trace_id,
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "sku_count": len(skus),
                "scrapers_filter": scrapers_filter,
            },
        )

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

            logger.info(
                f"[Chunk Worker] Completed chunk {chunk_index}: {chunk_results['skus_successful']}/{chunk_results['skus_processed']} successful",
                extra={
                    "job_id": job_id,
                    "trace_id": chunk_trace_id,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "skus_successful": chunk_results["skus_successful"],
                    "skus_processed": chunk_results["skus_processed"],
                },
            )

        except Exception as e:
            logger.exception(
                f"[Chunk Worker] Chunk {chunk_index} failed",
                extra={
                    "job_id": job_id,
                    "trace_id": chunk_trace_id,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            client.submit_chunk_results(chunk_id, "failed", error_message=str(e))
            chunks_processed += 1

    logger.info(
        f"[Chunk Worker] Finished. Total: {chunks_processed} chunks, {total_successful}/{total_skus_processed} successful",
        extra={
            "job_id": job_id,
            "trace_id": chunk_trace_id,
            "chunks_processed": chunks_processed,
            "total_successful": total_successful,
            "total_skus_processed": total_skus_processed,
        },
    )


async def run_realtime_mode(client: ScraperAPIClient, runner_name: str) -> None:
    """
    Realtime mode: Listen for jobs via Supabase Realtime and process them.

    Features:
    - Presence tracking (online/offline status)
    - Job progress broadcasting
    - Real-time log streaming
    - Heartbeat updates

    Supabase credentials are fetched via "credential vending" from the API.
    Falls back to environment variables if API fetch fails.

    Args:
        client: ScraperAPIClient instance for job config and result submission
        runner_name: Unique identifier for this runner instance
    """
    # Try to fetch Supabase config from API (credential vending)
    # Falls back to environment variables if API is unavailable
    supabase_config = client.get_supabase_config()

    if supabase_config:
        supabase_url = supabase_config.get("supabase_url")
        realtime_key = supabase_config.get("supabase_realtime_key")
        config_source = "API (credential vending)"
    else:
        # Fall back to environment variables
        realtime_key = os.environ.get("BSR_SUPABASE_REALTIME_KEY")
        supabase_url = os.environ.get("SUPABASE_URL")
        config_source = "environment variables"

    if not realtime_key:
        logger.error("[Realtime Runner] Supabase realtime key not configured", extra={"runner_name": runner_name})
        return

    if not supabase_url:
        logger.error("[Realtime Runner] Supabase URL not configured", extra={"runner_name": runner_name})
        return

    realtime_trace_id = generate_trace_id()
    logger.info(
        f"[Realtime Runner] Starting with runner name: {runner_name} (config source: {config_source})",
        extra={
            "runner_name": runner_name,
            "trace_id": realtime_trace_id,
        },
    )

    # Initialize RealtimeManager and connect
    rm = RealtimeManager(supabase_url, realtime_key, runner_name)

    connected = await rm.connect()
    if not connected:
        logger.error("[Realtime Runner] Failed to connect to Supabase Realtime", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
        return

    # Enable presence tracking
    presence_enabled = await rm.enable_presence()
    if not presence_enabled:
        logger.warning("[Realtime Runner] Failed to enable presence tracking", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})

    # Enable broadcast channels
    broadcast_enabled = await rm.enable_broadcast()
    if not broadcast_enabled:
        logger.warning("[Realtime Runner] Failed to enable broadcast channels", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})

    # Broadcast runner startup
    if rm._connected:
        await rm.broadcast_runner_status(
            status="starting",
            details={"message": "Runner initialized and waiting for jobs"},
        )

    async def on_job(job_data: dict) -> None:
        """Handle incoming job from Supabase Realtime."""
        job_id = job_data.get("job_id")
        job_lease_token: str | None = None
        if not job_id:
            logger.warning("[Realtime Runner] Received job without job_id", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
            return

        job_trace_id = generate_trace_id()
        logger.info(
            f"[Realtime Runner] Received job: {job_id}",
            extra={
                "job_id": job_id,
                "runner_name": runner_name,
                "trace_id": realtime_trace_id,
                "job_trace_id": job_trace_id,
            },
        )

        # Broadcast job started
        if rm._connected:
            await rm.broadcast_job_progress(
                job_id=job_id,
                status="started",
                progress=0,
                message="Job received and processing started",
            )
            await rm.broadcast_job_log(
                job_id=job_id,
                level="info",
                message=f"Runner {runner_name} started processing job",
            )

        try:
            # Update status to running
            client.update_status(job_id, "running", runner_name=runner_name)

            # Broadcast progress update
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="running",
                    progress=10,
                    message="Fetching job configuration",
                )

            # Fetch job configuration
            job_config = client.get_job_config(job_id)
            if not job_config:
                logger.error(
                    f"[Realtime Runner] Failed to fetch config for job {job_id}",
                    extra={
                        "job_id": job_id,
                        "runner_name": runner_name,
                        "trace_id": realtime_trace_id,
                        "job_trace_id": job_trace_id,
                        "error_type": "ConfigFetchError",
                    },
                )
                if rm._connected:
                    await rm.broadcast_job_progress(
                        job_id=job_id,
                        status="failed",
                        progress=0,
                        message="Failed to fetch job configuration",
                    )
                    await rm.broadcast_job_log(
                        job_id=job_id,
                        level="error",
                        message="Failed to fetch job configuration",
                    )
                client.submit_results(
                    job_id,
                    "failed",
                    runner_name=runner_name,
                    lease_token=job_data.get("lease_token"),
                    error_message="Failed to fetch job configuration",
                )
                return

            job_lease_token = job_config.lease_token

            # Broadcast that config was loaded
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="running",
                    progress=20,
                    message="Configuration loaded",
                    details={
                        "skus": len(job_config.skus),
                        "scrapers": [s.name for s in job_config.scrapers],
                    },
                )

            # Execute the job
            results = run_job(job_config, runner_name=runner_name)

            # Broadcast job completion
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="completed",
                    progress=100,
                    message="Job completed successfully",
                    details={
                        "skus_processed": results.get("skus_processed", 0),
                        "scrapers_run": results.get("scrapers_run", []),
                    },
                )
                await rm.broadcast_job_log(
                    job_id=job_id,
                    level="info",
                    message=f"Job completed: {results.get('skus_processed', 0)} SKUs processed",
                )

            # Submit results
            client.submit_results(
                job_id,
                "completed",
                runner_name=runner_name,
                lease_token=job_lease_token,
                results=results,
            )
            logger.info(
                f"[Realtime Runner] Job {job_id} completed successfully",
                extra={
                    "job_id": job_id,
                    "runner_name": runner_name,
                    "trace_id": realtime_trace_id,
                    "job_trace_id": job_trace_id,
                    "status": "completed",
                },
            )

        except ConfigValidationError as e:
            logger.error(
                f"[Realtime Runner] Config validation failed for job {job_id}: {e.message}",
                extra={
                    "job_id": job_id,
                    "runner_name": runner_name,
                    "trace_id": realtime_trace_id,
                    "job_trace_id": job_trace_id,
                    "error_type": "ConfigValidationError",
                    "config_slug": e.config_slug,
                    "schema_version": e.schema_version,
                },
            )
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="failed",
                    progress=0,
                    message=f"Config validation failed: {e.message}",
                )
                await rm.broadcast_job_log(
                    job_id=job_id,
                    level="error",
                    message=f"Config validation failed: {e.message}",
                )
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=job_lease_token,
                error_message=f"Config validation failed: {e.message}",
            )
        except ConfigFetchError as e:
            logger.error(
                f"[Realtime Runner] Config fetch failed for job {job_id}: {e}",
                extra={
                    "job_id": job_id,
                    "runner_name": runner_name,
                    "trace_id": realtime_trace_id,
                    "job_trace_id": job_trace_id,
                    "error_type": "ConfigFetchError",
                    "config_slug": getattr(e, "config_slug", None),
                },
            )
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="failed",
                    progress=0,
                    message=f"Config fetch failed: {e}",
                )
                await rm.broadcast_job_log(
                    job_id=job_id,
                    level="error",
                    message=f"Config fetch failed: {e}",
                )
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=job_lease_token,
                error_message=f"Config fetch failed: {e}",
            )
        except Exception as e:
            logger.exception(
                f"[Realtime Runner] Job {job_id} failed with error",
                extra={
                    "job_id": job_id,
                    "runner_name": runner_name,
                    "trace_id": realtime_trace_id,
                    "job_trace_id": job_trace_id,
                    "error_type": type(e).__name__,
                },
            )
            if rm._connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="failed",
                    progress=0,
                    message=f"Job failed: {str(e)}",
                )
                await rm.broadcast_job_log(
                    job_id=job_id,
                    level="error",
                    message=f"Job failed with error: {str(e)}",
                )
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=job_lease_token,
                error_message=str(e),
            )

    await rm.subscribe_to_jobs(on_job)

    logger.info("[Realtime Runner] Waiting for jobs... Press Ctrl+C to stop", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})

    try:
        # Keep running until interrupted
        await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("[Realtime Runner] Interrupted, shutting down...", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
    finally:
        # Broadcast shutdown
        if rm._connected:
            await rm.broadcast_runner_status(
                status="stopping",
                details={"message": "Runner shutting down"},
            )
        await rm.disconnect()
        logger.info("[Realtime Runner] Disconnected", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})


if __name__ == "__main__":
    main()
