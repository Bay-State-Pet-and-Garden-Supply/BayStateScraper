from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.api_client import JobConfig
from core.events import ScraperEvent, create_emitter, event_bus
from core.settings_manager import settings
from scrapers.ai_discovery import AIDiscoveryScraper
from scrapers.executor.workflow_executor import WorkflowExecutor
from scrapers.parser import ScraperConfigParser
from scrapers.result_collector import ResultCollector

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    pass


def create_log_entry(level: str, message: str) -> Dict[str, Any]:
    return {
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _normalize_selectors_payload(raw_selectors: Any) -> list[dict[str, Any]]:
    """Normalize API selectors payload into list format expected by ScraperConfig."""
    if isinstance(raw_selectors, list):
        return raw_selectors

    # API can return an empty object for "no selectors" in some paths.
    if raw_selectors is None or raw_selectors == {}:
        return []

    # Backward-compat for legacy dict format: {"Field": {"selector": "..."}}
    if isinstance(raw_selectors, dict):
        normalized: list[dict[str, Any]] = []
        for field_name, field_config in raw_selectors.items():
            if not isinstance(field_config, dict):
                continue
            item = dict(field_config)
            if "name" not in item and isinstance(field_name, str):
                item["name"] = field_name
            normalized.append(item)
        return normalized

    return []


def _build_telemetry_from_events(events: list[ScraperEvent]) -> Dict[str, Any]:
    steps_by_index: dict[int, dict[str, Any]] = {}
    selectors: list[dict[str, Any]] = []
    extractions: list[dict[str, Any]] = []

    for event in events:
        event_type = event.event_type.value
        data = event.data or {}

        if event_type in {"step.started", "step.completed", "step.failed", "step.skipped"}:
            raw_step_data = data.get("step")
            step_data: dict[str, Any] = raw_step_data if isinstance(raw_step_data, dict) else {}
            raw_timing_data = data.get("timing")
            timing_data: dict[str, Any] = raw_timing_data if isinstance(raw_timing_data, dict) else {}
            index = step_data.get("index")
            if not isinstance(index, int):
                continue

            existing = steps_by_index.get(
                index,
                {
                    "step_index": index,
                    "action_type": str(step_data.get("action") or "unknown"),
                    "status": "pending",
                    "extracted_data": {},
                },
            )

            action_value = step_data.get("action")
            if isinstance(action_value, str):
                existing["action_type"] = action_value

            if event_type == "step.started":
                existing["status"] = "running"
                started_at = timing_data.get("started_at")
                if isinstance(started_at, str):
                    existing["started_at"] = started_at
                elif isinstance(event.timestamp, str):
                    existing["started_at"] = event.timestamp
            elif event_type == "step.completed":
                existing["status"] = "completed"
                started_at = timing_data.get("started_at")
                completed_at = timing_data.get("completed_at")
                duration_ms = timing_data.get("duration_ms")
                if isinstance(started_at, str):
                    existing["started_at"] = started_at
                if isinstance(completed_at, str):
                    existing["completed_at"] = completed_at
                if isinstance(duration_ms, int):
                    existing["duration_ms"] = duration_ms
                raw_extraction_payload = data.get("extraction")
                extraction_payload: dict[str, Any] = raw_extraction_payload if isinstance(raw_extraction_payload, dict) else {}
                if extraction_payload:
                    existing["extracted_data"] = extraction_payload
                existing["sku"] = data.get("sku")
            elif event_type == "step.failed":
                existing["status"] = "failed"
                started_at = timing_data.get("started_at")
                completed_at = timing_data.get("completed_at")
                duration_ms = timing_data.get("duration_ms")
                if isinstance(started_at, str):
                    existing["started_at"] = started_at
                if isinstance(completed_at, str):
                    existing["completed_at"] = completed_at
                if isinstance(duration_ms, int):
                    existing["duration_ms"] = duration_ms
                raw_error_payload = data.get("error")
                error_payload: dict[str, Any] = raw_error_payload if isinstance(raw_error_payload, dict) else {}
                if isinstance(error_payload.get("message"), str):
                    existing["error_message"] = str(error_payload.get("message"))
                existing["sku"] = data.get("sku")
            elif event_type == "step.skipped":
                existing["status"] = "skipped"
                reason = data.get("reason")
                if isinstance(reason, str):
                    existing["error_message"] = reason
                existing["sku"] = data.get("sku")

            steps_by_index[index] = existing
            continue

        if event_type == "selector.resolved":
            raw_selector_payload = data.get("selector")
            selector_payload: dict[str, Any] = raw_selector_payload if isinstance(raw_selector_payload, dict) else {}
            found = selector_payload.get("found") is True
            status = "FOUND" if found else "MISSING"
            if isinstance(selector_payload.get("error"), str):
                status = "ERROR"

            selectors.append(
                {
                    "sku": data.get("sku") if isinstance(data.get("sku"), str) else "",
                    "selector_name": str(selector_payload.get("name") or "unknown"),
                    "selector_value": str(selector_payload.get("value") or ""),
                    "status": status,
                    "error_message": selector_payload.get("error") if isinstance(selector_payload.get("error"), str) else None,
                    "duration_ms": None,
                }
            )
            continue

        if event_type == "extraction.completed":
            raw_extraction_payload = data.get("extraction")
            extraction_payload: dict[str, Any] = raw_extraction_payload if isinstance(raw_extraction_payload, dict) else {}
            status = str(extraction_payload.get("status") or "SUCCESS")
            field_value = extraction_payload.get("value")
            extractions.append(
                {
                    "sku": data.get("sku") if isinstance(data.get("sku"), str) else "",
                    "field_name": str(extraction_payload.get("field_name") or "unknown"),
                    "field_value": str(field_value) if field_value is not None else None,
                    "status": status,
                    "error_message": extraction_payload.get("error") if isinstance(extraction_payload.get("error"), str) else None,
                    "duration_ms": None,
                }
            )

    ordered_steps = [steps_by_index[idx] for idx in sorted(steps_by_index.keys())]
    return {
        "steps": ordered_steps,
        "selectors": selectors,
        "extractions": extractions,
    }


def run_job(
    job_config: JobConfig,
    runner_name: Optional[str] = None,
    log_buffer: Optional[List[Dict[str, Any]]] = None,
    progress_callback: Optional[Callable[[str, str, dict[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """Execute a scrape job.

    Args:
        job_config: The job configuration
        runner_name: Optional name of the runner
        log_buffer: Optional list to collect log entries
        progress_callback: Optional callback function called after each SKU is processed.
                          Signature: callback(sku: str, scraper_name: str, data: dict) -> bool
                          Should return True if progress was saved successfully.

    Returns:
        Dictionary with job results
    """
    del runner_name

    job_id = job_config.job_id
    emitter = create_emitter(job_id)
    parser = ScraperConfigParser()
    collector = ResultCollector(test_mode=job_config.test_mode)

    results: Dict[str, Any] = {
        "skus_processed": 0,
        "scrapers_run": [],
        "data": {},
    }

    if log_buffer is None:
        log_buffer = []

    log_buffer.append(create_log_entry("info", f"Job {job_id} started"))
    log_buffer.append(create_log_entry("info", f"Processing {len(job_config.skus)} SKUs with {len(job_config.scrapers)} scrapers"))
    log_buffer.append(create_log_entry("info", f"Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}"))

    logger.info(f"[Runner] Starting job {job_id}")
    logger.info(f"[Runner] SKUs: {len(job_config.skus)}, Scrapers: {len(job_config.scrapers)}")
    logger.info(f"[Runner] Test mode: {job_config.test_mode}, Max workers: {job_config.max_workers}")

    skus = job_config.skus
    if not skus and job_config.test_mode:
        for scraper in job_config.scrapers:
            if scraper.test_skus:
                skus.extend(scraper.test_skus)
        skus = list(set(skus))
        log_buffer.append(create_log_entry("info", f"Test mode: using {len(skus)} test SKUs from job payload"))
        logger.info(f"[Runner] Test mode: using {len(skus)} test SKUs from job payload")

    if not skus:
        log_buffer.append(create_log_entry("warning", "No SKUs to process"))
        logger.warning("[Runner] No SKUs to process")
        results["logs"] = log_buffer
        results["telemetry"] = {"steps": [], "selectors": [], "extractions": []}
        return results

    is_discovery_job = job_config.job_type == "discovery" or any(s.name == "ai_discovery" for s in job_config.scrapers)
    if is_discovery_job:
        return _run_discovery_job(job_config, skus, results, log_buffer)

    configs: list[Any] = []
    config_errors: list[tuple[str, str]] = []

    for scraper_cfg in job_config.scrapers:
        try:
            options = scraper_cfg.options or {}
            config_dict = {
                "name": scraper_cfg.name,
                "base_url": scraper_cfg.base_url,
                "search_url_template": scraper_cfg.search_url_template,
                "selectors": _normalize_selectors_payload(scraper_cfg.selectors),
                "workflows": options.get("workflows", []),
                "timeout": options.get("timeout", 30),
                "test_skus": scraper_cfg.test_skus if scraper_cfg.test_skus is not None else [],
                "retries": getattr(scraper_cfg, "retries", 0),
                "validation": getattr(scraper_cfg, "validation", None),
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
        if not job_config.scrapers:
            error_msg = "No scrapers specified in job configuration (missing chunks?)"
        else:
            error_msg = f"No valid scraper configurations after filtering. Original scrapers: {[s.name for s in job_config.scrapers]}"
        log_buffer.append(create_log_entry("error", error_msg))
        raise ConfigurationError(f"[Runner] {error_msg}")

    for config in configs:
        log_buffer.append(create_log_entry("info", f"Starting scraper: {config.name}"))
        logger.info(f"[Runner] Running scraper: {config.name}")
        results["scrapers_run"].append(config.name)

        executor = None
        try:
            headless = settings.browser_settings["headless"]
            if not headless:
                logger.warning("[Runner] Running in VISIBLE mode (HEADLESS=false) - browser will be visible for debugging")
                log_buffer.append(create_log_entry("warning", "Running in VISIBLE mode - browser will be visible"))

            executor = WorkflowExecutor(
                config,
                headless=headless,
                timeout=30,
                worker_id="API",
                debug_mode=False,
                job_id=job_id,
                event_emitter=emitter,
            )

            # Run all async operations in a single event loop to properly manage
            # Playwright browser subprocess lifecycle
            async def run_all_scrapes() -> List[Tuple[str, Any]]:
                if executor is None:
                    return []
                scrape_results = []
                try:
                    await executor.initialize()
                    for sku in skus:
                        try:
                            result = await executor.execute_workflow(
                                context={"sku": sku, "test_mode": job_config.test_mode},
                                quit_browser=False,
                            )
                            scrape_results.append((sku, result))
                        except Exception as e:
                            log_buffer.append(create_log_entry("error", f"{config.name}/{sku}: {type(e).__name__} - {e}"))
                            logger.error(f"[Runner] {config.name}/{sku}: Error - {e}")
                            scrape_results.append((sku, None))
                finally:
                    # Ensure browser is properly quit inside the async context
                    if executor.browser:
                        try:
                            await executor.browser.quit()
                        except Exception as e:
                            logger.debug(f"Browser quit error: {e}")
                return scrape_results

            scrape_results = asyncio.run(run_all_scrapes())

            # Process results after async loop completes
            for sku, result in scrape_results:
                if result is None:
                    continue

                results["skus_processed"] += 1

                if result.get("success"):
                    extracted_data = result.get("results", {})

                    if extracted_data.get("product_name") and not extracted_data.get("Name"):
                        extracted_data["Name"] = extracted_data.pop("product_name")
                    if extracted_data.get("price") and not extracted_data.get("Price"):
                        extracted_data["Price"] = extracted_data.pop("price")
                    if extracted_data.get("brand") and not extracted_data.get("Brand"):
                        extracted_data["Brand"] = extracted_data.pop("brand")
                    if extracted_data.get("description") and not extracted_data.get("Description"):
                        extracted_data["Description"] = extracted_data.pop("description")
                    if extracted_data.get("image_url") and not extracted_data.get("Images"):
                        extracted_data["Images"] = [extracted_data.pop("image_url")]
                    if extracted_data.get("availability") and not extracted_data.get("Availability"):
                        extracted_data["Availability"] = extracted_data.pop("availability")
                    has_data = any(extracted_data.get(field) for field in ["Name", "Brand", "Weight"])

                    if has_data:
                        if sku not in results["data"]:
                            results["data"][sku] = {}

                        # Handle both "Images" and "Image URLs" field names
                        # (scraper configs use "Image URLs" as the selector name)
                        images = extracted_data.get("Images") or extracted_data.get("Image URLs") or extracted_data.get("Image_URLs") or []

                        # Capture the product page URL from the browser if not
                        # explicitly extracted by a "URL" selector
                        page_url = extracted_data.get("URL")
                        if not page_url and executor and executor.browser:
                            try:
                                page_url = executor.browser.current_url
                            except Exception:
                                pass

                        results["data"][sku][config.name] = {
                            # Note: Price is NOT scraped - we use our own pricing
                            "title": extracted_data.get("Name"),
                            "brand": extracted_data.get("Brand"),
                            "weight": extracted_data.get("Weight"),
                            "description": extracted_data.get("Description"),
                            "images": extracted_data.get("Image URLs", []) or extracted_data.get("Images", []),
                            "availability": extracted_data.get("Availability"),
                            "url": page_url,
                            "scraped_at": datetime.now().isoformat(),
                        }

                        collector.add_result(sku, config.name, extracted_data)

                        # Call progress callback if provided (for incremental saving)
                        if progress_callback:
                            try:
                                progress_callback(sku, config.name, results["data"][sku][config.name])
                            except Exception as e:
                                logger.warning(f"[Runner] Progress callback failed for {config.name}/{sku}: {e}")

                        log_buffer.append(create_log_entry("info", f"{config.name}/{sku}: Found data"))
                        emitter.info(f"{config.name}/{sku}: Found data", data=results["data"][sku][config.name])
                        logger.info(f"[Runner] {config.name}/{sku}: Found data")
                    else:
                        log_buffer.append(create_log_entry("info", f"{config.name}/{sku}: No data found"))
                        logger.info(f"[Runner] {config.name}/{sku}: No data found")
                else:
                    log_buffer.append(create_log_entry("warning", f"{config.name}/{sku}: Workflow failed"))
                    logger.warning(f"[Runner] {config.name}/{sku}: Workflow failed")

        except Exception as e:
            log_buffer.append(create_log_entry("error", f"Failed to initialize {config.name}: {e}"))
            logger.error(f"[Runner] Failed to initialize {config.name}: {e}")

    log_buffer.append(create_log_entry("info", f"Job complete. Processed {results['skus_processed']} SKUs"))
    logger.info(f"[Runner] Job complete. Processed {results['skus_processed']} SKUs")
    captured_events = event_bus.get_events(job_id=job_id, limit=2000)
    results["logs"] = log_buffer
    results["telemetry"] = _build_telemetry_from_events(captured_events)
    return results


def _run_discovery_job(
    job_config: JobConfig,
    skus: List[str],
    results: Dict[str, Any],
    log_buffer: List[Dict[str, Any]],
) -> Dict[str, Any]:
    discovery_cfg = job_config.job_config or {}
    scraper_name = "ai_discovery"
    max_concurrency = int(discovery_cfg.get("max_concurrency", job_config.max_workers) or job_config.max_workers)
    max_search_results = int(discovery_cfg.get("max_search_results", 5) or 5)
    max_steps = int(discovery_cfg.get("max_steps", 15) or 15)
    confidence_threshold = float(discovery_cfg.get("confidence_threshold", 0.7) or 0.7)
    llm_model = str(discovery_cfg.get("llm_model", "gpt-4o-mini") or "gpt-4o-mini")

    previous_openai = os.environ.get("OPENAI_API_KEY")
    previous_brave = os.environ.get("BRAVE_API_KEY")
    runtime_credentials = job_config.ai_credentials or {}
    runtime_openai = runtime_credentials.get("openai_api_key")
    runtime_brave = runtime_credentials.get("brave_api_key")

    if runtime_openai:
        os.environ["OPENAI_API_KEY"] = runtime_openai
    if runtime_brave:
        os.environ["BRAVE_API_KEY"] = runtime_brave

    item_context_by_sku: Dict[str, Dict[str, Any]] = {}

    raw_items = discovery_cfg.get("items")
    if isinstance(raw_items, list):
        for candidate in raw_items:
            if not isinstance(candidate, dict):
                continue
            candidate_sku = str(candidate.get("sku", "")).strip()
            if not candidate_sku:
                continue
            item_context_by_sku[candidate_sku] = candidate

    raw_sku_context = discovery_cfg.get("sku_context")
    if isinstance(raw_sku_context, dict):
        for key, value in raw_sku_context.items():
            candidate_sku = str(key).strip()
            if not candidate_sku or not isinstance(value, dict):
                continue
            merged_context = dict(item_context_by_sku.get(candidate_sku, {}))
            merged_context.update(value)
            merged_context.setdefault("sku", candidate_sku)
            item_context_by_sku[candidate_sku] = merged_context

    items = []
    for sku in skus:
        item_context = item_context_by_sku.get(sku, {})
        items.append(
            {
                "sku": sku,
                "product_name": item_context.get("product_name", discovery_cfg.get("product_name")),
                "brand": item_context.get("brand", discovery_cfg.get("brand")),
                "category": item_context.get("category", discovery_cfg.get("category")),
            }
        )

    log_buffer.append(create_log_entry("info", f"Starting discovery scraper for {len(items)} SKUs"))
    logger.info(f"[Runner] Starting discovery job for {len(items)} SKUs")
    results["scrapers_run"].append(scraper_name)

    async def _run() -> list[Any]:
        scraper = AIDiscoveryScraper(
            headless=settings.browser_settings["headless"],
            max_search_results=max_search_results,
            max_steps=max_steps,
            confidence_threshold=confidence_threshold,
            llm_model=llm_model,
        )
        return await scraper.scrape_products_batch(items, max_concurrency=max_concurrency)

    try:
        batch_results = asyncio.run(_run())
    finally:
        if runtime_openai:
            if previous_openai is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_openai

        if runtime_brave:
            if previous_brave is None:
                os.environ.pop("BRAVE_API_KEY", None)
            else:
                os.environ["BRAVE_API_KEY"] = previous_brave

    for discovery in batch_results:
        sku = discovery.sku
        results["skus_processed"] += 1
        if not sku:
            continue

        if sku not in results["data"]:
            results["data"][sku] = {}

        if discovery.success:
            results["data"][sku][scraper_name] = {
                "size_metrics": discovery.size_metrics,
                "title": discovery.product_name,
                "description": discovery.description,
                "images": discovery.images,
                "categories": discovery.categories,
                "url": discovery.url,
                "source_website": discovery.source_website,
                "confidence": discovery.confidence,
                "cost_usd": discovery.cost_usd,
                "scraped_at": datetime.now().isoformat(),
            }
            log_buffer.append(create_log_entry("info", f"{scraper_name}/{sku}: Found data"))
            logger.info(f"[Runner] {scraper_name}/{sku}: Found data")
        else:
            results["data"][sku][scraper_name] = {
                "error": discovery.error,
                "cost_usd": discovery.cost_usd,
                "scraped_at": datetime.now().isoformat(),
            }
            log_buffer.append(create_log_entry("warning", f"{scraper_name}/{sku}: {discovery.error or 'Failed'}"))
            logger.warning(f"[Runner] {scraper_name}/{sku}: {discovery.error or 'Failed'}")

    log_buffer.append(create_log_entry("info", f"Discovery job complete. Processed {results['skus_processed']} SKUs"))
    logger.info(f"[Runner] Discovery job complete. Processed {results['skus_processed']} SKUs")
    results["logs"] = log_buffer
    results["telemetry"] = {"steps": [], "selectors": [], "extractions": []}
    return results


__all__ = [
    "ConfigurationError",
    "create_emitter",
    "create_log_entry",
    "run_job",
]
