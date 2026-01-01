"""
New Modular Scraper System Entry Point

This module provides the main entry point for the new YAML-based modular scraper system.
It replaces the legacy archived scraper system.

Event System Integration:
    This module now emits structured events via the EventEmitter system in addition to
    legacy log callbacks. Events provide typed, JSON-serializable data that can be
    consumed by the frontend without regex parsing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime
from queue import Empty, Queue
from threading import Barrier, BrokenBarrierError, Lock
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scraper_backend.core.events import EventEmitter, create_emitter, event_bus
from scraper_backend.core.settings_manager import settings

if TYPE_CHECKING:
    pass  # EventEmitter is already imported above


def run_scraping(
    file_path: str | None = None,
    skus: list[str] | None = None,
    selected_sites: list[str] | None = None,
    log_callback=None,
    status_callback=None,
    progress_callback=None,
    scraper_progress_callback=None,
    scraper_workers: dict[str, int] | None = None,
    max_workers: int | None = None,
    test_mode: bool = False,
    debug_mode: bool = False,
    event_emitter: EventEmitter | None = None,
    debug_callback: Any | None = None,
    **kwargs,
) -> None:
    """
    Run scraping using the new modular scraper system.

    Args:
        file_path: Path to Excel file containing SKUs
        skus: List of SKUs to scrape (alternative to file_path)
        selected_sites: List of scraper names to use
        log_callback: Legacy callback for log messages
        status_callback: Legacy callback for status updates
        progress_callback: Legacy callback for progress percentage
        scraper_progress_callback: Legacy callback for per-scraper progress
        scraper_workers: Dict mapping scraper name to worker count
        max_workers: Maximum concurrent workers
        test_mode: If True, runs in test mode with detailed output
        event_emitter: Optional EventEmitter for structured events
    """
    # Force reload settings to pick up any recent changes (e.g. from settings.json edits)
    settings.reload()

    # Generate job ID for event correlation
    job_id = kwargs.get("job_id") or datetime.now().strftime("%Y%m%d_%H%M%S")

    # Initialize event emitter if not provided
    emitter = event_emitter or create_emitter(job_id)

    logger.info("Starting scraping with new modular scraper system...")

    # In test mode, use quiet logging unless debug is enabled
    quiet_mode = test_mode and not debug_mode

    if debug_mode:
        logging.basicConfig(level=logging.DEBUG, force=True)
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG) # Set root logger too just in case

    # Helper for logging
    def log(msg: str, level: str = "INFO", essential: bool = False) -> None:
        """Log a message. In quiet mode, only essential messages are printed."""
        # emit event for frontend visibility
        if emitter:
            if level == "INFO":
                emitter.info(msg, essential=essential)
            elif level == "WARNING":
                emitter.warning(msg)
            elif level == "ERROR":
                emitter.error(msg)
            elif level == "DEBUG" and debug_mode:  # only emit debug events if in debug mode
                emitter.info(msg, type="debug")

        # Always log errors and essential messages
        if quiet_mode and level not in ("ERROR", "WARNING") and not essential:
            # Still log to file, but don't print
            if level == "INFO":
                logger.info(msg)
            else:
                logger.debug(msg)
            return

        formatted_msg = f"[{level}] {msg}"
        if level == "INFO":
            logger.info(formatted_msg)
        elif level == "WARNING":
            logger.warning(formatted_msg)
        elif level == "ERROR":
            logger.error(formatted_msg)
        else:
            logger.debug(formatted_msg)

        if log_callback:
            try:
                log_callback.emit(formatted_msg)
            except AttributeError:
                log_callback(formatted_msg)

    # Helper for status updates
    def update_status(msg: str) -> None:
        if status_callback:
            try:
                status_callback.emit(msg)
            except AttributeError:
                status_callback(msg)

    # Helper for scraper progress updates
    def update_scraper_progress(data: dict) -> None:
        if scraper_progress_callback:
            if hasattr(scraper_progress_callback, "emit"):
                try:
                    scraper_progress_callback.emit(data)
                except Exception as e:
                    log(f"Failed to emit progress signal: {e}", "WARNING")
            else:
                scraper_progress_callback(data)

    # Load available scraper configurations
    available_sites = []
    remote_scrapers = []

    # Try to load from Supabase if available
    try:
        from scraper_backend.core.database.supabase_sync import supabase_sync

        if supabase_sync.initialize():
            remote_scrapers = supabase_sync.get_all_scrapers(include_disabled=False)
            # Use 'name' field
            for s in remote_scrapers:
                if "name" in s:
                    available_sites.append(s["name"])

            if available_sites:
                log(f"Found {len(available_sites)} scrapers in Supabase", "INFO")
    except ImportError:
        log("supabase sync not available.", "ERROR")
    except Exception as e:
        log(f"Failed to fetch from Supabase: {e}", "WARNING")

    if selected_sites:
        # Use user-selected sites but try to match with available ones if strictly required
        # For now, just trust selected_sites if provided, or filter available_sites
        # Legacy behavior was:
        available_sites = selected_sites

    if not available_sites:
        log("No scraper configurations found or selected.", "ERROR")
        return

    log(f"Available scrapers: {', '.join(available_sites)}")

    price_metadata = {}

    if skus:
        # Use provided SKUs
        log(f"Processing {len(skus)} SKUs (Direct Input)", "INFO")
        # TODO: If we need price metadata for direct input, it should be passed in kwargs or fetched
    elif file_path:
        # Load SKUs from Excel file
        update_status("Loading SKUs from Excel file...")
        try:
            from scraper_backend.scrapers.sku_loader import SKULoader

            loader = SKULoader()
            records = loader.load_with_context(file_path)
            skus = [r["SKU"] for r in records]

            # Extract Price metadata for preservation
            for record in records:
                sku = record.get("SKU", "")
                # Check for Price in various column names
                price = record.get("Price", record.get("LIST_PRICE", record.get("price", "")))
                if price:
                    price_metadata[sku] = price

            log(f"Loaded {len(skus)} SKUs from {file_path}", "INFO")
            if price_metadata:
                log(f"Found prices for {len(price_metadata)} products", "INFO")

            if not skus:
                log(
                    "No SKUs found in Excel file. Please ensure the file contains a 'SKU' column with values.",
                    "ERROR",
                )
                update_status("Error: No SKUs found in file")
                return

        except FileNotFoundError:
            log(f"Excel file not found: {file_path}", "ERROR")
            update_status("Error: File not found")
            return
        except Exception as e:
            log(f"Failed to load Excel file: {e}", "ERROR")
            update_status(f"Error: {e}")
            return
    elif test_mode:
        # In test mode without SKUs, we'll use each scraper's test_skus from config
        log("Test mode: SKUs will be loaded from scraper configs", "INFO")
        skus = []  # Will be populated per-scraper later
    else:
        log("No SKUs or Input File provided.", "ERROR")
        return

    # Database matches ShopSite (XML import). We do not modify it here.
    # We will pass the Excel prices to the consolidation step to store in consolidation_state.
    update_status("Verifying SKUs against database...")
    # (Optional: check which SKUs exist, but for now we just proceed to scrape)
    log(f"Processing {len(skus)} SKUs", "INFO")

    # Load scraper configurations
    update_status("Loading scraper configurations...")
    from scraper_backend.scrapers.executor.workflow_executor import WorkflowExecutor
    from scraper_backend.scrapers.parser import ScraperConfigParser
    from scraper_backend.scrapers.result_collector import ResultCollector

    parser = ScraperConfigParser()
    collector = ResultCollector(test_mode=test_mode)  # Collect results (skip saving if test_mode)
    configs = []

    # Map name to remote config dict for easy lookup
    remote_map = {s.get("name"): s for s in remote_scrapers}

    for site_name in available_sites:
        # Normalize site_name to snake_case for consistent lookup/filename
        normalized_name = site_name.lower().replace(" ", "_")

        try:
            # Try loading from Remote (Supabase) first
            if normalized_name in remote_map:
                config = parser.load_from_dict(remote_map[normalized_name])
                configs.append(config)
                log(f"Loaded config from Supabase: {config.name}", "INFO")
            elif site_name in remote_map:
                config = parser.load_from_dict(remote_map[site_name])
                configs.append(config)
                log(f"Loaded config from Supabase: {config.name}", "INFO")
            else:
                log(
                    f"Config not found for {site_name} in Supabase",
                    "WARNING",
                )

        except Exception as e:
            log(f"Failed to load config for {site_name}: {e}", "WARNING")

    if not configs:
        log("No valid scraper configurations loaded", "ERROR")
        return

    # Execute scraping
    total_operations = 0
    for config in configs:
        scraper_skus = skus if skus else (config.test_skus if test_mode and hasattr(config, 'test_skus') and config.test_skus else [])
        total_operations += len(scraper_skus)
        
    completed_operations = 0
    successful_results = 0
    failed_results = 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    MAX_WORKERS_DEFAULT = 2
    # Resolve max_workers with type-safe fallback
    resolved_workers: int = MAX_WORKERS_DEFAULT
    if max_workers is not None:
        resolved_workers = int(max_workers)
    else:
        setting_val = settings.get("max_workers", MAX_WORKERS_DEFAULT)
        resolved_workers = int(setting_val) if setting_val is not None else MAX_WORKERS_DEFAULT
    max_workers = resolved_workers

    # Emit JOB_STARTED event
    emitter.job_started(
        total_skus=total_operations,
        scrapers=[c.name for c in configs],
        max_workers=max_workers,
        test_mode=test_mode,
    )

    log(
        f"Starting job with {total_operations} total operations across {len(configs)} scrapers",
        "INFO",
    )

    # Get browser settings (Playwright)
    browser_timeout = settings.get("browser_timeout", settings.get("selenium_timeout", 30))

    log(f"Browser settings: headless=True, timeout={browser_timeout}s", "INFO")

    # If scraper_workers provided (from GUI), calculate total needed
    if scraper_workers:
        # Normalize keys for comparison (title case)
        normalized_workers = {k.title(): v for k, v in scraper_workers.items()}

        total_requested_workers = 0
        for c in configs:
            config_name_title = c.name.title()
            count = normalized_workers.get(config_name_title, 1)
            total_requested_workers += count

        log(f"Using user-defined worker counts (Total: {total_requested_workers})", "INFO")
        # Update max_workers to accommodate user request if needed
        if total_requested_workers > max_workers:
            max_workers = total_requested_workers
            log(f"   Increased max_workers to {max_workers} to match request", "INFO")
    else:
        log(f"Using max {max_workers} concurrent workers (Automatic allocation)", "INFO")

    # Allocation Strategy: Shared Work Queue per Scraper (enables work-stealing)
    # Instead of pre-splitting SKUs among workers, each scraper gets a shared queue
    # Workers pull from the queue until empty - fast workers automatically take more work

    scraper_queues: dict[str, Queue] = {}  # config.name -> Queue of SKUs
    tasks = []
    workers_used = 0

    # Calculate default workers per scraper based on available max_workers
    # Distribute available workers evenly among active scrapers
    default_workers_per_scraper = max(1, max_workers // len(configs))

    for config in configs:
        # Start with distributed default
        count = default_workers_per_scraper

        if test_mode:
            count = 1
            log(f"{config.name}: Enforcing 1 worker (Test Mode)", "INFO")

        if scraper_workers:
            # Normalize keys for comparison (title case)
            normalized_workers = {k.title(): v for k, v in scraper_workers.items()}
            config_name_title = config.name.title()

            if config_name_title in normalized_workers:
                count = normalized_workers[config_name_title]
                log(f"{config.name}: Matched worker count {count}", "DEBUG")

        # CRITICAL: Enforce single-threading for login sites
        if config.requires_login():
            if count > 1:
                log(f"{config.name}: Enforcing single-thread (Login Required)", "WARNING")
                count = 1
            else:
                log(f"{config.name}: Login required, keeping single-thread", "DEBUG")

        # Create a shared queue for this scraper's SKUs
        sku_queue: Queue = Queue()
        
        # In test mode with no provided SKUs, use scraper's configured test_skus
        scraper_skus = skus if skus else (config.test_skus if test_mode and hasattr(config, 'test_skus') and config.test_skus else [])
        
        if not scraper_skus:
            log(f"{config.name}: No SKUs to process (no input SKUs and no test_skus configured)", "WARNING")
            continue
            
        for sku in scraper_skus:
            sku_queue.put(sku)
        scraper_queues[config.name] = sku_queue

        if count > 1:
            log(f"{config.name}: {count} workers (shared queue with work-stealing)", "INFO")

            for i in range(count):
                # Stagger start times to prevent browser launch storms
                # 2 seconds delay per worker
                delay = workers_used * 2.0
                tasks.append((config, sku_queue, f"W{i + 1}", delay, len(scraper_skus)))
                workers_used += 1
        else:
            # Single worker
            delay = workers_used * 2.0
            tasks.append((config, sku_queue, "Main", delay, len(scraper_skus)))
            workers_used += 1
            log(f"{config.name}: 1 worker (sequential)", "INFO")

    log(f"Total active workers: {workers_used}", "INFO")

    # Thread-safe progress tracking
    progress_lock = Lock()

    # Synchronization barrier to ensure all browsers launch before scraping starts
    # This prevents "fast" workers from hogging CPU while "slow" workers are still launching
    start_barrier = Barrier(workers_used)

    # Inject barrier into tasks
    final_tasks = [(*t, start_barrier) for t in tasks]

    def process_scraper(args: tuple) -> dict | tuple[int, int]:
        """Process a scraper configuration by pulling SKUs from a shared queue (work-stealing)."""
        config, sku_queue, worker_id, start_delay, total_skus, barrier = args

        # Extract stop_event from parent scope kwargs
        stop_event = kwargs.get("stop_event")

        scraper_success = 0
        scraper_failed = 0
        skus_processed = 0
        worker_start_time = time.time()
        scraper_failed = 0
        skus_processed = 0
        worker_start_time = time.time()
        sku_timings = []  # Track individual SKU processing times
        test_details = []  # Track detailed results for test mode

        prefix = f"[{config.name}:{worker_id}]"

        # Staggered startup wait
        if start_delay > 0:
            log(f"{prefix} Waiting {start_delay:.1f}s to stagger startup...", "INFO")
            time.sleep(start_delay)

        worker_start_time = time.time()

        # Emit SCRAPER_STARTED event
        emitter.scraper_started(
            scraper=config.name,
            worker_id=worker_id,
            total_skus=total_skus,
        )

        log(f"\n{'=' * 60}", "INFO")
        log(
            f"Starting scraper: {config.name} ({worker_id}) - pulling from shared queue ({total_skus} total SKUs)",
            "INFO",
            essential=True,
        )
        log(f"{'=' * 60}", "INFO")

        update_status(f"Running {config.name} ({worker_id})...")
        update_scraper_progress(
            {
                "scraper": config.name,
                "worker_id": worker_id,
                "status": "running",
                "completed": 0,
                "failed": 0,
                "current_item": "Starting...",
            }
        )

        # Also emit worker progress event
        emitter.worker_progress(
            scraper=config.name,
            worker_id=worker_id,
            status="running",
            completed=0,
            failed=0,
            current_item="Starting...",
        )

        # Initialize executor for this scraper
        executor = None
        try:
            init_start = time.time()
            log(f"{prefix} Initializing browser/executor...", "INFO", essential=True)
            log(f"{prefix} Initializing browser/executor...", "INFO")
            executor = WorkflowExecutor(
                config,
                headless=True,
                timeout=browser_timeout,
                worker_id=worker_id,
                stop_event=stop_event,
                debug_mode=debug_mode,
                job_id=job_id,
                event_emitter=emitter,
                debug_callback=debug_callback,
            )
            init_duration = time.time() - init_start
            log(f"{prefix} Browser initialized in {init_duration:.2f}s", "INFO")

            # Emit browser init event
            emitter.browser_init(
                scraper=config.name,
                worker_id=worker_id,
                duration_seconds=init_duration,
            )
        except Exception as e:
            log(f"{prefix} Failed to initialize: {e}", "ERROR")
            # We continue to the barrier to not block other workers

        # Wait for all workers to be ready
        try:
            log(f"{prefix} Waiting for other workers to initialize...", "INFO")
            barrier.wait()

            # Post-barrier staggered delay to prevent thundering herd
            # Extract worker index for stagger calculation
            try:
                if worker_id.startswith("W"):
                    worker_index = int(worker_id[1:]) - 1  # W1 -> 0, W2 -> 1, etc.
                else:
                    worker_index = 0  # Main worker
            except (ValueError, IndexError):
                worker_index = 0

            post_barrier_delay = worker_index * 0.5  # 500ms stagger per worker
            if post_barrier_delay > 0:
                log(f"{prefix} Post-barrier stagger: {post_barrier_delay:.1f}s", "DEBUG")
                time.sleep(post_barrier_delay)

            log(f"{prefix} All workers ready! Starting scrape...", "INFO")
        except BrokenBarrierError:
            log(f"{prefix} Barrier broken, proceeding anyway...", "WARNING")

        # If initialization failed, return now
        if not executor:
            # Drain queue to prevent other workers from waiting forever
            drained = 0
            while not sku_queue.empty():
                try:
                    sku_queue.get_nowait()
                    drained += 1
                except Empty:
                    break
            return 0, drained

        # Process SKUs from the shared queue (work-stealing pattern)
        batch_size = 20
        log(f"{prefix} Starting to pull SKUs from shared queue...", "INFO")

        while True:
            # Check for cancellation
            if stop_event and stop_event.is_set():
                log(f"{prefix} Cancellation requested. Stopping...", "WARNING")
                break

            # Try to get next SKU from queue
            try:
                sku = sku_queue.get(timeout=0.5)  # Short timeout to allow checking stop_event
            except Empty:
                # Queue is empty, we're done
                log(f"{prefix} Queue empty, finishing up...", "INFO")
                break

            skus_processed += 1
            sku_start_time = time.time()

            # Restart browser every batch_size items
            if skus_processed > 1 and (skus_processed - 1) % batch_size == 0:
                log(f"{prefix} Restarting browser (batch limit {batch_size} reached)...", "INFO")
                try:
                    if executor.browser:
                        executor.browser.quit()
                    # Re-initialize executor (which creates new browser)
                    executor = WorkflowExecutor(
                        config,
                        headless=True,
                        timeout=browser_timeout,
                        worker_id=worker_id,
                        stop_event=stop_event,
                        debug_mode=debug_mode,
                        job_id=job_id,
                        event_emitter=emitter,
                    )
                except Exception as e:
                    log(f"{prefix} Failed to restart browser: {e}", "ERROR")
                    pass

            update_scraper_progress(
                {
                    "scraper": config.name,
                    "worker_id": worker_id,
                    "current_item": f"Processing {sku}",
                }
            )

            # Emit SKU_PROCESSING event
            emitter.sku_processing(scraper=config.name, worker_id=worker_id, sku=sku)

            try:
                # Initialize variables to ensure they exist in all code paths
                extracted_data = {}
                has_data = False
                no_results_found = False

                # Log current SKU for UI tracking
                if test_mode:
                    log(f"[CURRENT_SKU] {sku}", "INFO", essential=True)

                # Execute workflow with SKU context
                result = executor.execute_workflow(
                    context={"sku": sku, "test_mode": test_mode},
                    quit_browser=False,  # Reuse browser for efficiency
                )

                if result.get("success"):
                    extracted_data = result.get("results", {})
                    
                    # ALWAYS check for no_results (not just in test mode)
                    # Note: no_results_found is stored in self.results by CheckNoResultsAction
                    no_results_found = extracted_data.get("no_results_found", False)
                    
                    # Determine SKU type ONCE at the start
                    fake_skus_list = getattr(config, 'fake_skus', []) or []
                    sku_type = "fake" if sku in fake_skus_list else "test"

                    # In test mode, log selector results for the debugger (always, not just on success)
                    if test_mode:
                        # Ensure we log ALL expected selectors (found or missing)
                        expected_selectors = [s for s in config.selectors]
                        for selector in expected_selectors:
                            field = selector.name
                            value = extracted_data.get(field)
                            if value and value != "N/A" and value != []:
                                # Selector found
                                emitter.selector_found(
                                    scraper=config.name,
                                    sku=sku,
                                    selector_name=field,
                                    value=str(value),
                                )
                            else:
                                # Selector missing
                                emitter.selector_missing(
                                    scraper=config.name,
                                    sku=sku,
                                    selector_name=field,
                                )

                    # Check if we actually found product data (not just "no results")
                    has_data = any(
                        extracted_data.get(field) for field in ["Name", "Brand", "Weight"]
                    )
                    
                    # Determine outcome and is_passing using centralized logic
                    # Import the helper function from the new model
                    from scraper_backend.scrapers.models.result import calculate_is_passing
                    
                    if has_data:
                        outcome = "success"
                    elif no_results_found:
                        outcome = "no_results"
                    else:
                        outcome = "not_found"
                    
                    is_passing = calculate_is_passing(sku_type, outcome)
                    
                    # Calculate SKU duration for event
                    sku_duration = time.time() - sku_start_time
                    
                    # Update counters based on is_passing
                    if is_passing:
                        scraper_success += 1
                    else:
                        scraper_failed += 1
                    
                    # Emit appropriate event with sku_type and is_passing
                    if outcome == "success":
                        # Add to collector (JSON storage)
                        image_quality = result.get("image_quality", 50)
                        collector.add_result(
                            sku, config.name, extracted_data, image_quality=image_quality
                        )
                        
                        emitter.sku_success(
                            scraper=config.name,
                            worker_id=worker_id,
                            sku=sku,
                            data=extracted_data,
                            duration_seconds=sku_duration,
                            sku_type=sku_type,
                            is_passing=is_passing,
                        )
                        
                        if not test_mode:
                            supabase_sync.record_scrape_status(sku, config.name, "scraped")
                        else:
                            emitter.data_synced(sku=sku, scraper=config.name, data=extracted_data)
                        
                        name = extracted_data.get("Name", "N/A")
                        brand = extracted_data.get("Brand", "N/A")
                        weight = extracted_data.get("Weight", "N/A")
                        log(f"{prefix} Found: {name} | Brand: {brand} | Weight: {weight}", "INFO")
                        
                    elif outcome == "no_results":
                        emitter.sku_no_results(
                            scraper=config.name,
                            worker_id=worker_id,
                            sku=sku,
                            sku_type=sku_type,
                            is_passing=is_passing,
                        )
                        
                        if is_passing:
                            log(f"{prefix} Verified no results for fake SKU: {sku}", "INFO")
                        else:
                            log(f"{prefix} No results for test SKU (expected data): {sku}", "WARNING")
                        
                        if not test_mode:
                            status = "no_results" if is_passing else "not_found"
                            supabase_sync.record_scrape_status(sku, config.name, status)
                            
                    else:  # not_found
                        emitter.sku_not_found(
                            scraper=config.name,
                            worker_id=worker_id,
                            sku=sku,
                            sku_type=sku_type,
                            is_passing=is_passing,
                        )
                        
                        if not test_mode:
                            supabase_sync.record_scrape_status(sku, config.name, "not_found")
                else:
                    scraper_failed += 1
                    fake_skus_list = getattr(config, 'fake_skus', []) or []
                    sku_type = "fake" if sku in fake_skus_list else "test"
                    log(f"{prefix} Failed to scrape SKU: {sku}", "ERROR")

                    # Emit SKU_FAILED event
                    emitter.sku_failed(
                        scraper=config.name,
                        worker_id=worker_id,
                        sku=sku,
                        error="Workflow execution failed",
                        sku_type=sku_type,
                        is_passing=False,
                    )

                    # Record error status (Issue #87) - skip in test mode
                    if not test_mode:
                        supabase_sync.record_scrape_status(sku, config.name, "error")

                    # Emit selector_missing for all selectors on failure (always, for debug panel)
                    for s in config.selectors:
                        emitter.selector_missing(
                            scraper=config.name, sku=sku, selector_name=s.name
                        )

                if test_mode:
                    # Use already-computed values from centralized logic above
                    # sku_type, outcome, is_passing are already set
                    
                    # Map outcome to status for test details
                    if outcome == "success":
                        status = "success"
                    elif outcome == "no_results" and is_passing:
                        status = "no_results"  # Success for fake SKUs
                    else:
                        status = "failed"
                    
                    # Capture detail for this SKU
                    sku_detail = {
                        "sku": sku,
                        "sku_type": sku_type,
                        "outcome": outcome,
                        "is_passing": is_passing,
                        "status": status,
                        "selectors": {},
                        "data": extracted_data if has_data else {},
                    }

                    # Analyze selectors
                    for s in config.selectors:
                        if outcome == "no_results" and is_passing:
                            sku_detail["selectors"][s.name] = {
                                "status": "skipped",
                                "value": None
                            }
                        else:
                            val = extracted_data.get(s.name)
                            sku_detail["selectors"][s.name] = {
                                "status": "success" if val and val != "N/A" else "failed",
                                "value": str(val)[:100] if val else None,
                            }

                    test_details.append(sku_detail)

            except Exception as e:
                scraper_failed += 1
                log(f"{prefix} Error scraping SKU {sku}: {e}", "ERROR")

                # Emit SKU_FAILED event with exception details
                emitter.sku_failed(
                    scraper=config.name,
                    worker_id=worker_id,
                    sku=sku,
                    error=str(e),
                )

                # Record error with message (Issue #87) - skip in test mode
                if not test_mode:
                    supabase_sync.record_scrape_status(sku, config.name, "error", str(e))
                if test_mode:
                    # log(f"[SKU_RESULT] {sku}: ERROR", "INFO", essential=True)
                    # Capture error detail
                    test_details.append(
                        {
                            "sku": sku,
                            "status": "error",
                            "error": str(e),
                            "selectors": {
                                s.name: {"status": "failed", "value": None}
                                for s in config.selectors
                            },
                        }
                    )

            sku_duration = time.time() - sku_start_time
            sku_timings.append(sku_duration)
            log(
                f"{prefix} SKU {sku} took {sku_duration:.2f}s (processed: {skus_processed})",
                "DEBUG",
            )

            # Update progress (thread-safe)
            nonlocal completed_operations
            with progress_lock:
                completed_operations += 1
                current_ops = completed_operations
            if progress_callback and total_operations > 0:
                progress_pct = int((current_ops / total_operations) * 100)
                try:
                    progress_callback.emit(progress_pct)
                except AttributeError:
                    progress_callback(progress_pct)

            # Log progress for Docker parsing (legacy format for backwards compatibility)
            progress_pct = int((current_ops / total_operations) * 100) if total_operations > 0 else 100
            log(
                f"PROGRESS: {config.name} {current_ops} {total_operations} {progress_pct}% complete - processed {skus_processed} SKUs",
                "INFO",
                essential=True,
            )

            # Emit structured PROGRESS_UPDATE event
            emitter.progress_update(
                scraper=config.name,
                current=current_ops,
                total=total_operations,
                percentage=progress_pct,
                skus_processed=skus_processed,
            )

            # Send detailed update
            update_scraper_progress(
                {
                    "scraper": config.name,
                    "worker_id": worker_id,
                    "completed": scraper_success,
                    "failed": scraper_failed,
                    "current_item": f"Processed {sku}",
                }
            )

        # Cleanup browser for this scraper
        try:
            if executor and executor.browser:
                executor.browser.quit()
        except Exception as e:
            log(f"Error closing browser: {e}", "WARNING")

        worker_duration = time.time() - worker_start_time
        avg_sku_time = sum(sku_timings) / len(sku_timings) if sku_timings else 0.0

        log(
            f"Completed task: {config.name} ({worker_id}) - Processed {skus_processed} SKUs in {worker_duration:.1f}s (avg: {avg_sku_time:.2f}s/SKU)",
            "INFO",
        )

        # Emit SCRAPER_COMPLETED event
        emitter.scraper_completed(
            scraper=config.name,
            worker_id=worker_id,
            processed=skus_processed,
            successful=scraper_success,
            failed=scraper_failed,
            duration_seconds=worker_duration,
        )

        update_scraper_progress(
            {
                "scraper": config.name,
                "worker_id": worker_id,
                "status": "completed",
                "current_item": f"Done ({skus_processed} SKUs)",
            }
        )

        # Return stats for aggregation
        return {
            "success": scraper_success,
            "failed": scraper_failed,
            "processed": skus_processed,
            "duration": worker_duration,
            "avg_sku_time": avg_sku_time,
            "worker_id": worker_id,
            "scraper": config.name,
            "test_details": test_details,
        }

    # Initialize aggregation stats
    worker_stats = []
    successful_results = 0
    failed_results = 0

    # Run in thread pool
    with ThreadPoolExecutor(max_workers=workers_used) as thread_executor:
        futures = [thread_executor.submit(process_scraper, task) for task in final_tasks]

        for future in as_completed(futures):
            try:
                result = future.result()
                if isinstance(result, dict):
                    worker_stats.append(result)
                    successful_results += result["success"]
                    failed_results += result["failed"]
                else:
                    # Legacy tuple format (shouldn't happen but handle gracefully)
                    s_success, s_failed = result
                    successful_results += s_success
                    failed_results += s_failed
            except Exception as exc:
                log(f"Scraper task error: {exc}", "ERROR")

    # In TEST MODE: Aggregate and save detailed results to Supabase
    if test_mode and available_sites:
        try:
            # We assume one scraper is being tested at a time usually, but handle multiple
            # Group by scraper name
            scraper_results_map: dict[str, list[dict[str, Any]]] = {}

            for stat in worker_stats:
                s_name_raw = stat.get("scraper")
                if s_name_raw is None:
                    continue
                s_name = str(s_name_raw)
                if s_name not in scraper_results_map:
                    scraper_results_map[s_name] = []
                scraper_results_map[s_name].extend(stat.get("test_details", []))

            from scraper_backend.core.database.supabase_sync import supabase_sync

            for s_name, details in scraper_results_map.items():
                if not details:
                    continue

                # Calculate stats
                skus_status: dict[str, str] = {}
                selector_stats: dict[str, dict[str, int | str | None]] = {}

                # Get config to know all selectors (we need to find the config obj again)
                # Optimization: we could pass it, but lookup is fine
                s_config = next((c for c in configs if c.name == s_name), None)
                if not s_config:
                    continue

                # Init selector stats
                for sel in s_config.selectors:
                    selector_stats[sel.name] = {
                        "status": "unknown",
                        "success_count": 0,
                        "fail_count": 0,
                        "last_value": None,
                    }

                for d in details:
                    skus_status[d["sku"]] = d["status"]

                    # Update selector stats
                    for sel_name, sel_res in d.get("selectors", {}).items():
                        if sel_name not in selector_stats:
                            selector_stats[sel_name] = {"success_count": 0, "fail_count": 0}

                        if sel_res["status"] == "success":
                            prev_count = selector_stats[sel_name].get("success_count", 0)
                            selector_stats[sel_name]["success_count"] = (
                                int(prev_count) if prev_count is not None else 0
                            ) + 1
                            selector_stats[sel_name]["last_value"] = sel_res.get("value")
                        elif sel_res["status"] == "failed":
                            prev_count = selector_stats[sel_name].get("fail_count", 0)
                            selector_stats[sel_name]["fail_count"] = (
                                int(prev_count) if prev_count is not None else 0
                            ) + 1
                        # If status is "skipped" or "unknown", do not increment success or fail counts

                # Determine overall selector status
                for sel_name, sel_stats in selector_stats.items():
                    success_val = sel_stats.get("success_count", 0)
                    fail_val = sel_stats.get("fail_count", 0)
                    success_count = int(success_val) if success_val is not None else 0
                    fail_count = int(fail_val) if fail_val is not None else 0
                    total = success_count + fail_count
                    if total == 0:
                        sel_stats["status"] = "unknown"
                    elif success_count == total:
                        sel_stats["status"] = "success"
                    elif success_count > 0:
                        sel_stats["status"] = "mixed"  # or partial
                    else:
                        sel_stats["status"] = "failed"

                final_result = {
                    "timestamp": datetime.now().isoformat(),
                    "skus": skus_status,
                    "selectors": selector_stats,
                    "summary": {
                        "total": len(details),
                        "success": sum(1 for d in details if d["status"] == "success"),
                        "no_results": sum(1 for d in details if d["status"] == "no_results"),
                        "failed": sum(1 for d in details if d.get("status") in ("failed", "error")),
                    },
                }

                # Save test results to Supabase
                supabase_sync.update_scraper_test_result(s_name, final_result)

                # Calculate and update health status based on REQUIRED selectors only
                # Optional fields (required=False) don't affect health status
                # Note: 'required' may not be defined on SelectorConfig, default to True
                required_selectors = [sel for sel in s_config.selectors if getattr(sel, 'required', True)]
                
                # Use the centralized health calculation from the new model
                from scraper_backend.scrapers.models.result import SkuResult, calculate_health
                
                # Convert test details to SkuResult objects for health calculation
                sku_results = []
                for detail in details:
                    sku_results.append(SkuResult(
                        sku=detail["sku"],
                        sku_type=detail.get("sku_type", "test"),
                        outcome=detail.get("outcome", "failed"),
                        data=detail.get("data"),
                    ))
                
                # Check if fake SKUs are configured
                config_has_fake_skus = bool(getattr(s_config, 'fake_skus', None))
                
                # Calculate health using centralized logic
                health_status = calculate_health(sku_results, config_has_fake_skus)
                
                # Count passing results for the summary
                test_passing = sum(1 for r in sku_results if r.sku_type == "test" and r.is_passing)
                fake_passing = sum(1 for r in sku_results if r.sku_type == "fake" and r.is_passing)
                total_passing = test_passing + fake_passing

                # Update health status
                supabase_sync.update_scraper_health(s_name, {
                    "status": health_status,
                    "last_tested": final_result["timestamp"],
                    "selectors_passed": sum(1 for s in selector_stats.values() if s.get("status") in ("success", "mixed")),
                    "selectors_total": len(selector_stats),
                    "test_skus_passed": total_passing,
                    "test_skus_total": final_result["summary"]["total"],
                    "selectors": [
                        {
                            "name": name,
                            "status": stat.get("status", "unknown"),
                            "value": stat.get("last_value"),
                            "success_count": stat.get("success_count", 0),
                            "fail_count": stat.get("fail_count", 0),
                        }
                        for name, stat in selector_stats.items()
                    ],
                })
                log(f"Updated health status for {s_name}: {health_status}", "INFO")

        except Exception as e:
            log(f"Failed to save test results to Supabase: {e}", "ERROR")

    # Save results to database
    try:
        collector.save_session(metadata={"price": price_metadata})

        # Display collection stats - essential in test mode
        stats = collector.get_stats()
        log("", "INFO", essential=True)
        log("RESULTS SUMMARY", "INFO", essential=True)
        log(f"  Unique SKUs found: {stats['total_unique_skus']}", "INFO", essential=True)
        log(f"  Total scraper results: {stats['total_results']}", "INFO", essential=True)
        log(
            f"  SKUs found on multiple sites: {stats['skus_found_on_multiple_sites']}",
            "INFO",
            essential=True,
        )
    except Exception as e:
        log(f"Failed to save results: {e}", "ERROR")

    # Legacy SQLite staging removed - data is synced to Supabase via ResultCollector
    if test_mode:
        log("Skipping consolidation (test mode)", "INFO", essential=True)
    else:
        log("Data synced to Supabase via ResultCollector", "INFO")

    # Display worker performance statistics (work-stealing effectiveness)
    if worker_stats:
        log("\nWorker Performance Statistics:", "INFO")
        log("-" * 60, "INFO")
        for stat in sorted(worker_stats, key=lambda x: x.get("processed", 0), reverse=True):
            worker_id = stat.get("worker_id", "?")
            scraper = stat.get("scraper", "?")
            processed = stat.get("processed", 0)
            duration = stat.get("duration", 0)
            avg_time = stat.get("avg_sku_time", 0)
            success = stat.get("success", 0)
            failed = stat.get("failed", 0)
            rate = processed / duration if duration > 0 else 0
            log(
                f"   [{scraper}:{worker_id}] Processed: {processed} SKUs | "
                f"Duration: {duration:.1f}s | Rate: {rate:.2f} SKU/s | "
                f"Avg: {avg_time:.2f}s/SKU | Success: {success} | Failed: {failed}",
                "INFO",
            )
        log("-" * 60, "INFO")

        # Check for imbalance
        if len(worker_stats) > 1:
            processed_counts = [s.get("processed", 0) for s in worker_stats]
            max_processed = max(processed_counts)
            min_processed = min(processed_counts)
            if max_processed > 0 and min_processed > 0:
                imbalance_ratio = max_processed / min_processed
                if imbalance_ratio > 1.5:
                    log(
                        f"Worker imbalance detected: {imbalance_ratio:.1f}x difference (max: {max_processed}, min: {min_processed})",
                        "WARNING",
                    )
                else:
                    log(f"Worker balance good: {imbalance_ratio:.1f}x difference", "INFO")

    # Final summary
    job_duration = time.time() - emitter._start_time

    # Emit JOB_COMPLETED event
    emitter.job_completed(
        successful=successful_results,
        failed=failed_results,
        duration_seconds=job_duration,
    )

    log(f"\n{'=' * 60}", "INFO")
    log("SCRAPING COMPLETE", "INFO")
    log(f"{'=' * 60}", "INFO")
    log(f"Total operations: {total_operations}", "INFO")
    log(f"Successful: {successful_results}", "INFO")
    log(f"Failed: {failed_results}", "INFO")
    if total_operations > 0:
        log(f"Success rate: {(successful_results / total_operations * 100):.1f}%", "INFO")
    else:
        log("Success rate: N/A (no operations)", "INFO")

    update_status("Scraping complete!")
