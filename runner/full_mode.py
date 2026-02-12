from __future__ import annotations

import json
import logging
import sys

from core.api_client import ScraperAPIClient
from core.config_fetcher import ConfigFetchError, ConfigValidationError
from utils.structured_logging import generate_trace_id

from runner import run_job

logger = logging.getLogger(__name__)


def run_full_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    trace_id = generate_trace_id()
    logger.info(
        f"[Full Mode] Starting job {job_id}",
        extra={"job_id": job_id, "trace_id": trace_id, "runner_name": runner_name},
    )
    client.update_status(job_id, "running", runner_name=runner_name)

    job_config = client.get_job_config(job_id)
    if not job_config:
        logger.error(
            "Failed to fetch job config",
            extra={
                "job_id": job_id,
                "trace_id": trace_id,
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
        print(json.dumps(results, indent=2))
    except ConfigValidationError as e:
        logger.error(
            f"[Full Mode] Config validation failed: {e}",
            extra={
                "job_id": job_id,
                "trace_id": trace_id,
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
            error_message=f"Config validation failed for {e.config_slug}: {e}",
        )
        sys.exit(1)
    except ConfigFetchError as e:
        logger.error(
            f"[Full Mode] Config fetch failed: {e}",
            extra={
                "job_id": job_id,
                "trace_id": trace_id,
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
                "trace_id": trace_id,
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
