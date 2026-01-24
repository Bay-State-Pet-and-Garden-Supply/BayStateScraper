"""
Docker Scraper API

Minimal FastAPI server for Docker-based scraper communication.
Allows frontend to start/stop/monitor scraping jobs.

Event System Integration:
    This server now uses the structured event system for observability.
    Events are exposed via the /events endpoint for the frontend to consume.
"""

from __future__ import annotations


import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# Ensure backend is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scraper_backend.core.events import (
    EventType,
    ScraperEvent,
    create_emitter,
    event_bus,
)

logger = logging.getLogger(__name__)

# =============================================================================
# State Management
# =============================================================================


class JobState:
    """State for tracking scraper jobs."""

    def __init__(self):
        self.is_running = False
        self.job_id: str | None = None
        self.progress = 0.0
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.started_at: datetime | None = None
        self.stop_event: threading.Event | None = None
        self.active_scrapers: set[str] = set()
        self.total_skus = 0
        self.completed_skus = 0
        self.worker_stats: dict[
            str, dict
        ] = {}  # worker_id -> {scraper, current_sku, completed, failed}
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.is_running = False
            self.job_id = None
            self.progress = 0.0
            self.logs = []
            self.errors = []
            self.started_at = None
            self.stop_event = None
            self.active_scrapers = set()
            self.total_skus = 0
            self.completed_skus = 0
            self.worker_stats = {}

    def start_job(self, job_id: str) -> threading.Event:
        with self._lock:
            self.is_running = True
            self.job_id = job_id
            self.progress = 0.0
            self.logs = []
            self.errors = []
            self.started_at = datetime.now()
            self.stop_event = threading.Event()
            self.active_scrapers = set()
            self.total_skus = 0
            self.completed_skus = 0
            self.worker_stats = {}
            return self.stop_event

    def add_log(self, message: str):
        with self._lock:
            self.logs.append(message)
            # Keep only last 100 logs
            if len(self.logs) > 100:
                self.logs = self.logs[-100:]

    def add_error(self, message: str):
        with self._lock:
            self.errors.append(message)

    def update_progress(self, progress: float):
        with self._lock:
            self.progress = min(100.0, max(0.0, progress))

    def add_active_scraper(self, name: str):
        with self._lock:
            self.active_scrapers.add(name)

    def remove_active_scraper(self, name: str):
        with self._lock:
            self.active_scrapers.discard(name)

    def set_totals(self, total_skus: int):
        with self._lock:
            self.total_skus = total_skus
            self.completed_skus = 0

    def increment_completed(self):
        with self._lock:
            self.completed_skus += 1
            # Progress is now updated explicitly via update_progress from the scraper engine callbacks
            # if self.total_skus > 0:
            #     self.progress = (self.completed_skus / self.total_skus) * 100

    def update_worker(self, worker_id: str, data: dict):
        with self._lock:
            self.worker_stats[worker_id] = data

    def finish(self):
        with self._lock:
            self.is_running = False
            self.progress = 100.0
            self.active_scrapers = set()

    def to_dict(self) -> dict:
        with self._lock:
            # Calculate ETA based on elapsed time and progress
            eta_seconds = None
            if self.started_at and self.progress > 0:
                elapsed = (datetime.now() - self.started_at).total_seconds()
                remaining_pct = 100 - self.progress
                if remaining_pct > 0:
                    eta_seconds = int((elapsed / self.progress) * remaining_pct)

            return {
                "is_running": self.is_running,
                "job_id": self.job_id,
                "progress": round(self.progress, 1),
                "logs": list(self.logs[-50:]),  # Last 50 logs
                "errors": list(self.errors),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "active_scrapers": list(self.active_scrapers),
                "total_skus": self.total_skus,
                "completed_skus": self.completed_skus,
                "eta_seconds": eta_seconds,
                "workers": dict(self.worker_stats),
            }


def get_job_state() -> JobState:
    """Dependency to get JobState from app state."""
    if not hasattr(app.state, "job_state"):
        app.state.job_state = JobState()
    state: JobState = app.state.job_state
    return state


# Type alias for job state dependency injection (avoids B008 ruff warning)
JobStateDep = Annotated[JobState, Depends(get_job_state)]


# =============================================================================
# Request/Response Models
# =============================================================================


class ScrapeRequest(BaseModel):
    skus: list[str]
    scrapers: list[str]
    max_workers: int = 2
    test_mode: bool = False
    debug_mode: bool = False  # Enable verbose logging and artifact capture

    @field_validator("skus")
    @classmethod
    def validate_skus(cls, v):
        # Allow empty SKUs list - in test mode, SKUs may come from scraper config
        if len(v) > 1000:
            raise ValueError("Too many SKUs (max 1000)")
        return v

    @field_validator("scrapers")
    @classmethod
    def validate_scrapers(cls, v):
        if not v:
            raise ValueError("Scrapers list cannot be empty")
        if len(v) > 50:
            raise ValueError("Too many scrapers (max 50)")
        return v

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v):
        if v < 1 or v > 10:
            raise ValueError("max_workers must be between 1 and 10")
        return v


class ScrapeResponse(BaseModel):
    status: str
    job_id: str
    message: str


class StatusResponse(BaseModel):
    is_running: bool
    job_id: str | None
    progress: float
    logs: list[str]
    errors: list[str]
    started_at: str | None
    active_scrapers: list[str] = []
    total_skus: int = 0
    completed_skus: int = 0
    eta_seconds: int | None = None
    workers: dict = {}


class StopResponse(BaseModel):
    status: str
    message: str


# =============================================================================
# Scraper Runner (Background Task)
# =============================================================================


def run_scraper_job(
    job_state: JobState,
    skus: list[str],
    scrapers: list[str],
    max_workers: int,
    test_mode: bool,
    debug_mode: bool,
    stop_event: threading.Event,
    job_id: str,
):
    """Run the scraper in a background task."""
    try:
        from scraper_backend.api.debug_context import debug_context
        from scraper_backend.scrapers.main import run_scraping

        # Create an event emitter for this job
        emitter = create_emitter(job_id)

        # Start debug session if debug mode enabled
        if debug_mode:
            debug_context.start_session(job_id, debug_mode=True)
            logger.info(f"Debug mode enabled for job {job_id}")

        # SKU totals and active scrapers are set in start_scrape before this task starts

        def log_callback(msg: str):
            job_state.add_log(msg)
            # Also add to debug context if in debug mode
            if debug_mode:
                debug_context.log(job_id, msg)

        def progress_callback(pct: int):
            # Use the percentage calculated by the scraper engine
            job_state.update_progress(pct)
            # Also increment completed counter for tracking (optional, but good for stats)
            job_state.increment_completed()

        def scraper_progress_callback(data: dict):
            worker_id = f"{data.get('scraper')}:{data.get('worker_id', 'Main')}"
            job_state.update_worker(worker_id, data)
            # If status is completed, remove from active
            if data.get("status") == "completed":
                job_state.remove_active_scraper(data.get("scraper", ""))

        def debug_callback(data: dict):
            """Callback for debug snapshots (source/screenshot)."""
            if debug_mode:
                debug_context.capture_snapshot(
                    job_id=job_id,
                    sku=str(data.get("sku")) if data.get("sku") else "unknown",
                    page_source=str(data.get("page_source"))
                    if data.get("page_source")
                    else None,
                    screenshot=str(data.get("screenshot"))
                    if data.get("screenshot")
                    else None,
                )

        run_scraping(
            skus=skus,
            selected_sites=scrapers,
            max_workers=max_workers,
            test_mode=test_mode,
            log_callback=log_callback,
            progress_callback=progress_callback,
            scraper_progress_callback=scraper_progress_callback,
            stop_event=stop_event,
            event_emitter=emitter,
            job_id=job_id,
            debug_mode=debug_mode,
            debug_callback=debug_callback,
        )

        job_state.finish()
        job_state.add_log("Scraping completed successfully")

        # End debug session
        if debug_mode:
            debug_context.end_session(job_id)

    except Exception as e:
        job_state.add_error(str(e))
        job_state.finish()
        logger.error(f"Scraper job failed: {e}")
        # Emit job failed event
        try:
            emitter = create_emitter(job_id)
            emitter.job_failed(error=str(e))
        except Exception:
            pass  # Don't fail if event emission fails


# =============================================================================
# FastAPI App
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    logger.info("Docker Scraper API starting...")
    yield
    logger.info("Docker Scraper API shutting down...")


app = FastAPI(
    title="Docker Scraper API",
    description="API for controlling Docker-based scrapers",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend access (restrict to localhost for security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "tauri://localhost",
    ],  # Restrict to local origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.post("/scrape", response_model=ScrapeResponse)
async def start_scrape(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    job_state: JobStateDep,
):
    """Start a scraping job."""
    if job_state.is_running:
        raise HTTPException(status_code=409, detail="A scraping job is already running")

    # Generate job ID
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Start the job
    stop_event = job_state.start_job(job_id)

    # Initialize SKU count and active scrapers BEFORE background task starts
    # This prevents a race condition where status is fetched before initialization
    job_state.set_totals(len(request.skus))
    for scraper in request.scrapers:
        job_state.add_active_scraper(scraper)

    # Run scraper in background task
    background_tasks.add_task(
        run_scraper_job,
        job_state,
        request.skus,
        request.scrapers,
        request.max_workers,
        request.test_mode,
        request.debug_mode,
        stop_event,
        job_id,
    )

    return ScrapeResponse(
        status="started",
        job_id=job_id,
        message=f"Started scraping {len(request.skus)} SKUs with {len(request.scrapers)} scrapers",
    )


@app.get("/status", response_model=StatusResponse)
async def get_status(job_state: JobStateDep):
    """Get the current scraper status."""
    state = job_state.to_dict()
    return StatusResponse(**state)


@app.post("/stop", response_model=StopResponse)
async def stop_scrape(job_state: JobStateDep):
    """Stop the running scraper job."""
    if not job_state.is_running:
        return StopResponse(
            status="not_running",
            message="No scraper job is currently running",
        )

    # Signal the stop event
    if job_state.stop_event:
        job_state.stop_event.set()

    job_state.add_log("Stop requested by user")

    return StopResponse(
        status="stopping",
        message="Stop signal sent to scraper",
    )


@app.get("/scrapers")
async def list_scrapers():
    """List available scrapers from local YAML configs."""
    configs_dir = os.path.join(project_root, "scrapers", "configs")
    scrapers = []

    if os.path.exists(configs_dir):
        for filename in os.listdir(configs_dir):
            if (
                filename.endswith((".yaml", ".yml"))
                and filename != "sample_config.yaml"
            ):
                name = filename.replace(".yaml", "").replace(".yml", "")
                scrapers.append(
                    {
                        "name": name,
                        "display_name": name.replace("_", " ").title(),
                    }
                )

    return {"scrapers": scrapers}


# =============================================================================
# Events Endpoint (Structured Event System)
# =============================================================================


class EventsResponse(BaseModel):
    """Response model for events endpoint."""

    events: list[dict]
    total: int
    has_more: bool


@app.get("/events")
async def get_events(
    job_id: str | None = Query(None, description="Filter events by job ID"),
    event_types: str | None = Query(
        None, description="Comma-separated event types to filter"
    ),
    since: str | None = Query(None, description="ISO timestamp to get events after"),
    limit: int = Query(100, ge=1, le=500, description="Maximum events to return"),
):
    """Get structured events from the event bus.

    This endpoint replaces log parsing with typed, JSON events that the frontend
    can consume directly without regex.

    Event types include:
    - job.started, job.completed, job.failed, job.cancelled
    - scraper.started, scraper.completed, scraper.failed
    - sku.processing, sku.success, sku.not_found, sku.failed
    - progress.update, progress.worker
    - selector.found, selector.missing
    - data.synced, data.sync_failed
    - system.info, system.warning, system.error
    """
    # Parse event types filter
    type_filter = None
    if event_types:
        try:
            type_filter = [EventType(t.strip()) for t in event_types.split(",")]
        except ValueError:
            pass  # Ignore invalid event types

    events = event_bus.get_events_as_dicts(
        job_id=job_id,
        event_types=type_filter,
        since=since,
        limit=limit + 1,  # Get one extra to check if there's more
    )

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    return EventsResponse(
        events=events,
        total=len(events),
        has_more=has_more,
    )


@app.get("/events/types")
async def list_event_types():
    """List all available event types."""
    return {
        "event_types": [e.value for e in EventType],
        "categories": {
            "job": [e.value for e in EventType if e.value.startswith("job.")],
            "scraper": [e.value for e in EventType if e.value.startswith("scraper.")],
            "sku": [e.value for e in EventType if e.value.startswith("sku.")],
            "progress": [e.value for e in EventType if e.value.startswith("progress.")],
            "selector": [e.value for e in EventType if e.value.startswith("selector.")],
            "data": [e.value for e in EventType if e.value.startswith("data.")],
            "system": [e.value for e in EventType if e.value.startswith("system.")],
        },
    }


# =============================================================================
# Test Endpoints
# =============================================================================


class TestRequest(BaseModel):
    """Request model for running scraper tests."""

    config_id: str | None = None
    scraper_name: str | None = None
    skus: list[str] | None = None
    headless: bool = True

    @field_validator("skus")
    @classmethod
    def validate_skus(cls, v):
        if v and len(v) > 20:
            raise ValueError("Too many SKUs for test (max 20)")
        return v if v else []


class TestResultSku(BaseModel):
    """Individual SKU test result."""

    sku: str
    sku_type: str  # "test" or "fake"
    status: str  # "success", "no_results", "failed", "error"
    is_passing: bool
    outcome: str
    selectors: dict[str, dict[str, str | None]]  # selector_name -> {status, value}
    data: dict[str, str] | None = None
    error: str | None = None


class TestResultSelector(BaseModel):
    """Selector-level test result."""

    name: str
    status: str  # "success", "failed", "mixed", "unknown", "skipped"
    success_count: int
    fail_count: int
    last_value: str | None = None


class TestResponse(BaseModel):
    """Response model for test results."""

    status: str
    scraper_name: str
    success: bool
    summary: dict[str, int]  # total, success, no_results, failed
    skus: list[TestResultSku]
    selectors: dict[str, TestResultSelector]
    execution_time_seconds: float
    timestamp: str
    errors: list[str] = []


@app.post("/test", response_model=TestResponse)
async def run_test(
    request: TestRequest,
    background_tasks: BackgroundTasks,
    job_state: JobStateDep,
):
    """Run a scraper test and return detailed results.

    This endpoint runs a scraper in test mode, executing against configured
    test_skus (or provided SKUs) and returning detailed results including
    selector-level analysis.
    """
    import uuid
    from datetime import datetime

    # Determine scraper name from config_id or scraper_name
    scraper_name = request.scraper_name

    if not scraper_name and not request.config_id:
        raise HTTPException(
            status_code=400, detail="Either config_id or scraper_name must be provided"
        )

    # If config_id provided, fetch the scraper name from Supabase
    if request.config_id and not scraper_name:
        try:
            from scraper_backend.core.database.supabase_sync import supabase_sync

            if supabase_sync.initialize():
                config = supabase_sync.get_scraper_by_id(request.config_id)
                if config and config.get("slug"):
                    scraper_name = config["slug"]
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Config with ID {request.config_id} not found",
                    )
        except ImportError:
            raise HTTPException(status_code=500, detail="Supabase sync not available")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch config: {str(e)}"
            )

    if not scraper_name:
        raise HTTPException(status_code=400, detail="Could not determine scraper name")

    # Check if a test is already running
    if job_state.is_running:
        raise HTTPException(status_code=409, detail="A scraping job is already running")

    # Generate job ID
    job_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Start the job
    stop_event = job_state.start_job(job_id)

    # Initialize job state
    job_state.set_totals(len(request.skus) if request.skus else 1)
    job_state.add_active_scraper(scraper_name)

    test_results: dict = {}
    test_results_lock = threading.Lock()

    def test_log_callback(msg: str):
        job_state.add_log(msg)

    def test_progress_callback(pct: int):
        job_state.update_progress(pct)
        job_state.increment_completed()

    def test_scraper_progress_callback(data: dict):
        worker_id = f"{data.get('scraper')}:{data.get('worker_id', 'Main')}"
        job_state.update_worker(worker_id, data)
        if data.get("status") == "completed":
            job_state.remove_active_scraper(data.get("scraper", ""))

    def collect_test_results(result: dict):
        """Collect test results from the scraper execution."""
        with test_results_lock:
            # Extract test_details from the result
            test_details = result.get("test_details", [])
            scraper_stats = {
                "scraper": result.get("scraper", scraper_name),
                "success": result.get("success", 0),
                "failed": result.get("failed", 0),
                "processed": result.get("processed", 0),
                "duration": result.get("duration", 0),
                "test_details": test_details,
            }
            test_results["stats"] = scraper_stats
            test_results["timestamp"] = datetime.now().isoformat()

    async def run_test_job():
        """Run the actual test in a thread pool."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                await loop.run_in_executor(
                    executor,
                    lambda: _execute_test_job(
                        scraper_name=scraper_name,
                        skus=request.skus,
                        headless=request.headless,
                        log_callback=test_log_callback,
                        progress_callback=test_progress_callback,
                        scraper_progress_callback=test_scraper_progress_callback,
                        stop_event=stop_event,
                        job_id=job_id,
                        results_collector=collect_test_results,
                    ),
                )
            except Exception as e:
                job_state.add_error(str(e))
            finally:
                job_state.finish()

    # Run test in background
    background_tasks.add_task(run_test_job)

    # Wait for test to complete (with timeout)
    # For now, return immediately with the job ID so frontend can poll
    return TestResponse(
        status="started",
        scraper_name=scraper_name,
        success=False,  # Will be updated when test completes
        summary={"total": 0, "success": 0, "no_results": 0, "failed": 0},
        skus=[],
        selectors={},
        execution_time_seconds=0.0,
        timestamp=datetime.now().isoformat(),
        errors=[],
    )


def _execute_test_job(
    scraper_name: str,
    skus: list[str] | None,
    headless: bool,
    log_callback,
    progress_callback,
    scraper_progress_callback,
    stop_event: threading.Event,
    job_id: str,
    results_collector,
):
    """Execute the actual test job (runs in thread pool)."""
    import time
    from datetime import datetime

    start_time = time.time()

    try:
        from scraper_backend.api.debug_context import debug_context
        from scraper_backend.scrapers.main import run_scraping
        from scraper_backend.core.events import create_emitter

        # Create event emitter
        emitter = create_emitter(job_id)

        # Start debug session
        debug_context.start_session(job_id, debug_mode=False)
        logger.info(f"Test mode enabled for job {job_id}")

        # Run scraping in test mode
        run_scraping(
            selected_sites=[scraper_name],
            skus=skus if skus else None,  # Will use test_skus from config if None
            max_workers=1,
            test_mode=True,
            debug_mode=False,
            log_callback=log_callback,
            progress_callback=progress_callback,
            scraper_progress_callback=scraper_progress_callback,
            stop_event=stop_event,
            event_emitter=emitter,
            job_id=job_id,
            debug_callback=None,
        )

        # End debug session
        debug_context.end_session(job_id)

    except Exception as e:
        log_callback(f"Test failed: {e}")
        logger.error(f"Test job failed: {e}")

    execution_time = time.time() - start_time
    logger.info(f"Test completed in {execution_time:.2f}s")


@app.get("/test/{scraper_name}/results", response_model=TestResponse)
async def get_test_results(
    scraper_name: str,
    job_id: str | None = Query(None, description="Specific job ID to get results for"),
):
    """Get test results for a scraper.

    This endpoint retrieves the most recent test results from Supabase
    where they are automatically saved when tests complete.
    """
    try:
        from scraper_backend.core.database.supabase_sync import supabase_sync

        if not supabase_sync.initialize():
            raise HTTPException(status_code=503, detail="Supabase not available")

        # Get the most recent test result for this scraper
        # This comes from the scraper_health table where test results are stored
        health = supabase_sync.get_scraper_health(scraper_name)

        if not health:
            raise HTTPException(
                status_code=404,
                detail=f"No test results found for scraper: {scraper_name}",
            )

        # Parse the health data to extract test results
        last_tested = health.get("last_tested")
        selectors_data = health.get("selectors", [])

        # Build selector results from health data
        selectors: dict[str, TestResultSelector] = {}
        for sel in selectors_data:
            selectors[sel["name"]] = TestResultSelector(
                name=sel["name"],
                status=sel.get("status", "unknown"),
                success_count=sel.get("success_count", 0),
                fail_count=sel.get("fail_count", 0),
                last_value=sel.get("last_value"),
            )

        return TestResponse(
            status="completed",
            scraper_name=scraper_name,
            success=health.get("status") == "healthy",
            summary={
                "total": health.get("test_skus_total", 0),
                "success": health.get("test_skus_passed", 0),
                "no_results": 0,  # Not stored separately in health
                "failed": health.get("test_skus_total", 0)
                - health.get("test_skus_passed", 0),
            },
            skus=[],  # SKU-level details not persisted in health, only summary
            selectors=selectors,
            execution_time_seconds=0.0,  # Not stored
            timestamp=last_tested or datetime.now().isoformat(),
            errors=[],
        )

    except ImportError:
        raise HTTPException(status_code=500, detail="Supabase sync not available")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get test results: {str(e)}"
        )


# =============================================================================
# Debug Endpoints
# =============================================================================


@app.get("/debug/session")
async def get_debug_session(
    job_id: str | None = Query(
        None, description="Job ID (uses current if not specified)"
    ),
):
    """Get debug session info."""
    from scraper_backend.api.debug_context import debug_context

    session_info = debug_context.get_session_info(job_id)
    if not session_info:
        return {"status": "no_session", "message": "No debug session found"}
    return {"status": "ok", "session": session_info}


@app.get("/debug/page-source")
async def get_debug_page_source(
    job_id: str | None = Query(
        None, description="Job ID (uses current if not specified)"
    ),
):
    """Get the current page source HTML from the debug context."""
    from scraper_backend.api.debug_context import debug_context

    page_source = debug_context.get_current_page_source(job_id)
    if not page_source:
        return {
            "status": "not_available",
            "message": "No page source captured. Enable debug mode when running tests.",
            "page_source": None,
        }
    return {
        "status": "ok",
        "page_source": page_source,
        "length": len(page_source),
    }


@app.get("/debug/screenshot")
async def get_debug_screenshot(
    job_id: str | None = Query(
        None, description="Job ID (uses current if not specified)"
    ),
):
    """Get the current browser screenshot (base64 encoded)."""
    from scraper_backend.api.debug_context import debug_context

    screenshot = debug_context.get_current_screenshot(job_id)
    if not screenshot:
        return {
            "status": "not_available",
            "message": "No screenshot captured. Enable debug mode when running tests.",
            "screenshot": None,
        }
    return {
        "status": "ok",
        "screenshot": screenshot,
        "format": "base64/png",
    }


@app.get("/debug/logs")
async def get_debug_logs(
    job_id: str | None = Query(
        None, description="Job ID (uses current if not specified)"
    ),
    limit: int = Query(100, ge=1, le=500, description="Maximum logs to return"),
):
    """Get verbose debug logs from the current session."""
    from scraper_backend.api.debug_context import debug_context

    logs = debug_context.get_verbose_logs(job_id, limit=limit)
    return {
        "status": "ok",
        "logs": logs,
        "count": len(logs),
    }


@app.get("/debug/snapshots")
async def get_debug_snapshots(
    job_id: str | None = Query(
        None, description="Job ID (uses current if not specified)"
    ),
    sku: str | None = Query(None, description="Filter by SKU"),
    limit: int = Query(20, ge=1, le=100, description="Maximum snapshots to return"),
):
    """Get debug snapshots (page sources and screenshots) from the current session."""
    from scraper_backend.api.debug_context import debug_context

    snapshots = debug_context.get_snapshots(job_id, sku=sku, limit=limit)
    return {
        "status": "ok",
        "snapshots": snapshots,
        "count": len(snapshots),
    }


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
