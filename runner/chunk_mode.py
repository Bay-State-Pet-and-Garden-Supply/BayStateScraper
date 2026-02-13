from __future__ import annotations

import logging

from core.api_client import ScraperAPIClient

from runner import run_job

logger = logging.getLogger(__name__)


def run_chunk_worker_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    logger.info(f"[Chunk Worker] Starting for job {job_id}")

    chunks_processed = 0
    total_skus_processed = 0
    total_successful = 0

    # Fetch job config ONCE before the loop - don't refetch for every chunk
    job_config = client.get_job_config(job_id)
    if not job_config:
        raise RuntimeError("Failed to fetch initial job config")

    logger.info(f"[Chunk Worker] Loaded job config: {len(job_config.skus)} SKUs, {len(job_config.scrapers)} scrapers")

    while True:
        chunk = client.claim_chunk(job_id=job_id, runner_name=runner_name)
        if not chunk:
            logger.info(f"[Chunk Worker] No more chunks. Processed {chunks_processed} chunks, {total_skus_processed} SKUs")
            break

        chunk_id = chunk.chunk_id
        chunk_index = chunk.chunk_index
        skus = chunk.skus
        scrapers_filter = chunk.scrapers

        if chunk.job_id != job_id:
            logger.info(f"[Chunk Worker] Skipping chunk from job {chunk.job_id}; expected {job_id}")
            continue

        logger.info(f"[Chunk Worker] Processing chunk {chunk_index} with {len(skus)} SKUs")

        try:
            # Reuse the cached job_config instead of fetching again
            # Just update the SKUs for this specific chunk
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

            logger.info(f"[Chunk Worker] Completed chunk {chunk_index}: {chunk_results['skus_successful']}/{chunk_results['skus_processed']} successful")
        except Exception as e:
            logger.exception(f"[Chunk Worker] Chunk {chunk_index} failed")
            client.submit_chunk_results(chunk_id, "failed", error_message=str(e))
            chunks_processed += 1

    logger.info(f"[Chunk Worker] Finished. Total: {chunks_processed} chunks, {total_successful}/{total_skus_processed} successful")
