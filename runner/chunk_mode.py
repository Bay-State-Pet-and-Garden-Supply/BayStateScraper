from __future__ import annotations

import logging

from core.api_client import JobConfig, ScraperAPIClient

from runner import run_job

logger = logging.getLogger(__name__)


def run_chunk_worker_mode(client: ScraperAPIClient, job_id: str, runner_name: str) -> None:
    logger.info(f"[Chunk Worker] Starting for job {job_id}")

    chunks_processed = 0
    total_skus_processed = 0
    total_successful = 0

    # Fetch job config ONCE before the loop - don't refetch for every chunk
    base_job_config = client.get_job_config(job_id)
    if not base_job_config:
        raise RuntimeError("Failed to fetch initial job config")

    logger.info(f"[Chunk Worker] Loaded job config: {len(base_job_config.skus)} SKUs, {len(base_job_config.scrapers)} scrapers")
    base_scrapers_by_name = {scraper.name: scraper for scraper in base_job_config.scrapers}

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

        # Track partial results for incremental saving
        partial_results: dict[str, dict[str, dict]] = {}
        skus_successful = 0
        skus_failed = 0

        def progress_callback(sku: str, scraper_name: str, data: dict) -> bool:
            """Callback invoked after each SKU is processed. Saves progress incrementally."""
            nonlocal skus_successful

            # Store in partial results
            if sku not in partial_results:
                partial_results[sku] = {}
            partial_results[sku][scraper_name] = data
            skus_successful += 1

            # Submit progress to API (fire and forget - don't block on failure)
            try:
                client.submit_chunk_progress(chunk_id, sku, scraper_name, data)
                logger.debug(f"[Chunk Worker] Saved progress for {scraper_name}/{sku}")
                return True
            except Exception as e:
                logger.warning(f"[Chunk Worker] Failed to save progress for {scraper_name}/{sku}: {e}")
                return False

        try:
            # Build isolated per-chunk config (do not mutate shared base config)
            selected_scrapers = list(base_job_config.scrapers)
            if scrapers_filter:
                selected_scrapers = [base_scrapers_by_name[name] for name in scrapers_filter if name in base_scrapers_by_name]
                missing_scrapers = [name for name in scrapers_filter if name not in base_scrapers_by_name]
                if missing_scrapers:
                    logger.warning(
                        f"[Chunk Worker] Chunk {chunk_index} referenced unknown scrapers: {missing_scrapers}. "
                        f"Available scrapers: {list(base_scrapers_by_name.keys())}"
                    )

            if not selected_scrapers:
                available_scrapers = list(base_scrapers_by_name.keys())
                raise RuntimeError(f"Chunk {chunk_index} resolved to zero scrapers. Requested filter={scrapers_filter}, available={available_scrapers}")

            chunk_job_config = JobConfig(
                job_id=base_job_config.job_id,
                skus=list(skus),
                scrapers=selected_scrapers,
                test_mode=base_job_config.test_mode,
                max_workers=base_job_config.max_workers,
                job_type=base_job_config.job_type,
                job_config=base_job_config.job_config,
                ai_credentials=base_job_config.ai_credentials,
                lease_token=chunk.lease_token or base_job_config.lease_token,
                lease_expires_at=chunk.lease_expires_at or base_job_config.lease_expires_at,
            )

            # Run job with progress callback for incremental saving
            results = run_job(chunk_job_config, runner_name=runner_name, progress_callback=progress_callback)

            # Calculate final results (including any SKUs that weren't captured by callback)
            final_data = results.get("data", {})
            for sku, scraper_data in final_data.items():
                if sku not in partial_results:
                    partial_results[sku] = scraper_data
                    skus_successful += 1
                else:
                    # Merge any missing scraper data
                    for scraper_name, data in scraper_data.items():
                        if scraper_name not in partial_results[sku]:
                            partial_results[sku][scraper_name] = data
                            skus_successful += 1

            skus_processed = len(skus)
            skus_failed = skus_processed - skus_successful

            chunk_results = {
                "skus_processed": skus_processed,
                "skus_successful": skus_successful,
                "skus_failed": skus_failed,
                "data": partial_results,
            }

            client.submit_chunk_results(chunk_id, "completed", results=chunk_results)

            chunks_processed += 1
            total_skus_processed += skus_processed
            total_successful += skus_successful

            logger.info(f"[Chunk Worker] Completed chunk {chunk_index}: {skus_successful}/{skus_processed} successful")
        except Exception as e:
            logger.exception(f"[Chunk Worker] Chunk {chunk_index} failed")
            # Even on failure, save any partial results we collected
            if partial_results:
                logger.info(f"[Chunk Worker] Saving {len(partial_results)} partial results before failing")
                partial_chunk_results = {
                    "skus_processed": len(skus),
                    "skus_successful": skus_successful,
                    "skus_failed": len(skus) - skus_successful,
                    "data": partial_results,
                }
                client.submit_chunk_results(chunk_id, "failed", results=partial_chunk_results, error_message=str(e))
            else:
                client.submit_chunk_results(chunk_id, "failed", error_message=str(e))
            chunks_processed += 1

    logger.info(f"[Chunk Worker] Finished. Total: {chunks_processed} chunks, {total_successful}/{total_skus_processed} successful")
