from __future__ import annotations

import logging
import os
from typing import Any

from core.api_client import ScraperAPIClient
from core.config_fetcher import ConfigFetchError, ConfigValidationError
from core.realtime_manager import RealtimeManager
from utils.structured_logging import generate_trace_id

from runner import run_job

logger = logging.getLogger(__name__)


async def run_realtime_mode(client: ScraperAPIClient, runner_name: str) -> None:
    supabase_config = client.get_supabase_config()
    if supabase_config:
        supabase_url = supabase_config.get("supabase_url")
        realtime_key = supabase_config.get("supabase_realtime_key")
        config_source = "api"
    else:
        realtime_key = os.environ.get("BSR_SUPABASE_REALTIME_KEY")
        supabase_url = os.environ.get("SUPABASE_URL")
        config_source = "env"

    if not realtime_key:
        logger.error("[Realtime Runner] Supabase realtime key not configured", extra={"runner_name": runner_name})
        return
    if not supabase_url:
        logger.error("[Realtime Runner] Supabase URL not configured", extra={"runner_name": runner_name})
        return

    realtime_trace_id = generate_trace_id()
    logger.info(
        f"[Realtime Runner] Starting with runner name: {runner_name} ({config_source})",
        extra={"runner_name": runner_name, "trace_id": realtime_trace_id},
    )

    rm = RealtimeManager(supabase_url, realtime_key, runner_name)

    connected = await rm.connect()
    if not connected:
        logger.error("[Realtime Runner] Failed to connect to Supabase Realtime", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
        return

    if not await rm.enable_presence():
        logger.warning("[Realtime Runner] Failed to enable presence tracking", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
    if not await rm.enable_broadcast():
        logger.warning("[Realtime Runner] Failed to enable broadcast channels", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})

    if rm.is_connected:
        await rm.broadcast_runner_status(
            status="starting",
            details={"message": "Runner initialized and waiting for jobs"},
        )

    async def handle_job(job_data: dict[str, Any]) -> None:
        job_id = job_data.get("job_id")
        if not job_id:
            logger.warning("[Realtime Runner] Received job without job_id", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
            return

        job_trace_id = generate_trace_id()
        lease_token: str | None = None

        logger.info(
            f"[Realtime Runner] Received job: {job_id}",
            extra={
                "job_id": job_id,
                "runner_name": runner_name,
                "trace_id": realtime_trace_id,
                "job_trace_id": job_trace_id,
            },
        )

        if rm.is_connected:
            await rm.broadcast_job_progress(job_id=job_id, status="started", progress=0, message="Job received")
            await rm.broadcast_job_log(job_id=job_id, level="info", message=f"Runner {runner_name} started processing job")

        try:
            client.update_status(job_id, "running", runner_name=runner_name)

            if rm.is_connected:
                await rm.broadcast_job_progress(job_id=job_id, status="running", progress=10, message="Fetching job configuration")

            job_config = client.get_job_config(job_id)
            if not job_config:
                if rm.is_connected:
                    await rm.broadcast_job_progress(job_id=job_id, status="failed", progress=0, message="Failed to fetch job configuration")
                    await rm.broadcast_job_log(job_id=job_id, level="error", message="Failed to fetch job configuration")
                client.submit_results(
                    job_id,
                    "failed",
                    runner_name=runner_name,
                    lease_token=job_data.get("lease_token"),
                    error_message="Failed to fetch job configuration",
                )
                return

            lease_token = job_config.lease_token

            if rm.is_connected:
                await rm.broadcast_job_progress(
                    job_id=job_id,
                    status="running",
                    progress=20,
                    message="Configuration loaded",
                    details={"skus": len(job_config.skus), "scrapers": [s.name for s in job_config.scrapers]},
                )

            results = run_job(job_config, runner_name=runner_name)

            if rm.is_connected:
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
                await rm.broadcast_job_log(job_id=job_id, level="info", message=f"Job completed: {results.get('skus_processed', 0)} SKUs processed")

            client.submit_results(
                job_id,
                "completed",
                runner_name=runner_name,
                lease_token=lease_token,
                results=results,
            )
        except ConfigValidationError as e:
            if rm.is_connected:
                await rm.broadcast_job_progress(job_id=job_id, status="failed", progress=0, message=f"Config validation failed: {e}")
                await rm.broadcast_job_log(job_id=job_id, level="error", message=f"Config validation failed: {e}")
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=lease_token,
                error_message=f"Config validation failed: {e}",
            )
        except ConfigFetchError as e:
            if rm.is_connected:
                await rm.broadcast_job_progress(job_id=job_id, status="failed", progress=0, message=f"Config fetch failed: {e}")
                await rm.broadcast_job_log(job_id=job_id, level="error", message=f"Config fetch failed: {e}")
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=lease_token,
                error_message=f"Config fetch failed: {e}",
            )
        except Exception as e:
            logger.exception(
                f"[Realtime Runner] Job {job_id} failed with error",
                extra={"job_id": job_id, "runner_name": runner_name, "trace_id": realtime_trace_id, "job_trace_id": job_trace_id},
            )
            if rm.is_connected:
                await rm.broadcast_job_progress(job_id=job_id, status="failed", progress=0, message=f"Job failed: {e}")
                await rm.broadcast_job_log(job_id=job_id, level="error", message=f"Job failed with error: {e}")
            client.submit_results(
                job_id,
                "failed",
                runner_name=runner_name,
                lease_token=lease_token,
                error_message=str(e),
            )

    def on_job(job_data: dict[str, Any]) -> None:
        import asyncio

        asyncio.create_task(handle_job(job_data))

    await rm.subscribe_to_jobs(on_job)
    logger.info("[Realtime Runner] Waiting for jobs... Press Ctrl+C to stop", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})

    try:
        import asyncio

        await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("[Realtime Runner] Interrupted, shutting down...", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
    finally:
        if rm.is_connected:
            await rm.broadcast_runner_status(status="stopping", details={"message": "Runner shutting down"})
        await rm.disconnect()
        logger.info("[Realtime Runner] Disconnected", extra={"runner_name": runner_name, "trace_id": realtime_trace_id})
