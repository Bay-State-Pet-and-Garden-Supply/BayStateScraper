"""
Workflow executor for scraper automation using Playwright.

This module has been refactored to use extracted modules for better separation of concerns:
- BrowserManager: Browser lifecycle management
- SelectorResolver: Element finding and value extraction
- DebugArtifactCapture: Debug artifact capture
- NormalizationEngine: Result normalization
- StepExecutor: Step execution with retry logic
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from core.adaptive_retry_strategy import AdaptiveRetryStrategy
from core.anti_detection_manager import AntiDetectionManager
from core.failure_analytics import FailureAnalytics
from core.failure_classifier import FailureClassifier, FailureType
from core.retry_executor import CircuitBreakerConfig, RetryExecutor
from core.settings_manager import PROJECT_ROOT, SettingsManager
from scrapers.actions import ActionRegistry
from scrapers.exceptions import (
    BrowserError,
    CircuitBreakerOpenError,
    ErrorContext,
    NoResultsError,
    NonRetryableError,
    PageNotFoundError,
    ScraperError,
    WorkflowExecutionError,
)
from scrapers.models.config import ScraperConfig, SelectorConfig, WorkflowStep

# Extracted modules
from scrapers.executor.browser_manager import BrowserManager
from scrapers.executor.selector_resolver import SelectorResolver
from scrapers.executor.debug_capture import DebugArtifactCapture
from scrapers.executor.normalization import NormalizationEngine
from scrapers.executor.step_executor import StepExecutor

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Executes scraper workflows defined in YAML configurations using Playwright."""

    def __init__(
        self,
        config: ScraperConfig,
        headless: bool = True,
        timeout: int | None = None,
        enable_retry: bool = True,
        max_retries: int | None = None,
        worker_id: str | None = None,
        stop_event: threading.Event | None = None,
        debug_mode: bool = False,
        job_id: str | None = None,
        event_emitter: Any | None = None,
        debug_callback: Any | None = None,
    ) -> None:
        """
        Initialize the workflow executor.

        Args:
            config: ScraperConfig instance with workflow definition
            headless: Whether to run browser in headless mode
            timeout: Default timeout in seconds (overrides config timeout)
            enable_retry: Whether to enable retry logic for actions
            max_retries: Override default max retries (uses config.retries if None)
            worker_id: Optional identifier for the worker (used for profile isolation)
            stop_event: Optional threading.Event to check for cancellation
        """
        self.config = config
        self.headless = headless
        self.enable_retry = enable_retry
        self.worker_id = worker_id
        self.stop_event = stop_event
        self.debug_mode = debug_mode
        self.job_id = job_id
        self.event_emitter = event_emitter
        self.debug_callback = debug_callback
        self.settings = SettingsManager()

        # Determine if running in CI environment (must be set before timeout logic)
        self.is_ci: bool = os.getenv("CI") == "true"

        self.timeout = timeout or config.timeout

        # Increase timeout in CI environment for more reliable testing
        if self.is_ci:
            self.timeout = 60

        # Set max retries from config or parameter
        self.max_retries = max_retries if max_retries is not None else config.retries

        self.browser: Any = None
        self.results: dict[str, Any] = {}
        self.context: dict[str, Any] = {}  # Store execution context

        # Build selector lookup dictionaries (ID-based primary, name-based fallback)
        self.selectors_by_id: dict[str, SelectorConfig] = {s.id: s for s in config.selectors if s.id}
        self.selectors: dict[str, SelectorConfig] = {s.name: s for s in config.selectors}

        self.anti_detection_manager: AntiDetectionManager | None = None

        # Initialize adaptive retry strategy with history persistence
        history_path = os.path.join(PROJECT_ROOT, "data", f"retry_history_{config.name}.json")
        self.adaptive_retry_strategy = AdaptiveRetryStrategy(history_file=history_path)

        # Initialize failure classifier with site-specific patterns
        no_results_selectors = self.config.validation.no_results_selectors if self.config.validation else []
        no_results_text_patterns = self.config.validation.no_results_text_patterns if self.config.validation else []
        self.failure_classifier = FailureClassifier(
            site_specific_no_results_selectors=no_results_selectors,
            site_specific_no_results_text_patterns=no_results_text_patterns,
        )

        # Initialize failure analytics
        self.failure_analytics = FailureAnalytics()

        # Initialize retry executor with circuit breaker
        circuit_config = CircuitBreakerConfig(
            failure_threshold=5,  # Open circuit after 5 consecutive failures
            success_threshold=2,  # Close after 2 successes
            timeout_seconds=60.0,  # Try again after 60s
        )
        self.retry_executor = RetryExecutor(
            adaptive_strategy=self.adaptive_retry_strategy,
            failure_analytics=self.failure_analytics,
            failure_classifier=self.failure_classifier,
            circuit_breaker_config=circuit_config,
        )

        # Register recovery handlers
        self._register_recovery_handlers()

        # Initialize action registry with auto-discovery
        ActionRegistry.auto_discover_actions()

        # Track workflow state
        self.first_navigation_done = False
        self.workflow_stopped = False
        self.current_step_index = 0

        # Session management for login persistence
        self.session_authenticated = False
        self.session_auth_time: float | None = None
        self.session_timeout = 1800  # 30 minutes default session timeout

        # Error tracking for current workflow run
        self.step_errors: list[dict[str, Any]] = []

        # Extracted modules will be initialized in async initialize()
        self.selector_resolver: SelectorResolver | None = None
        self.debug_capture: DebugArtifactCapture | None = None
        self.normalization_engine: NormalizationEngine | None = None
        self.step_executor: StepExecutor | None = None

    async def initialize(self) -> None:
        """Initialize the browser and all extracted modules asynchronously."""
        # Initialize browser
        try:
            import uuid

            # Use random UUID for profile path to ensure isolation (Old Setup)
            # This prevents locking issues at the cost of no persistence
            profile_suffix = f"workflow_{int(time.time())}_{uuid.uuid4().hex[:8]}"

            backend = "playwright"

            if backend == "playwright":
                from utils.scraping.playwright_browser import (
                    create_playwright_browser,
                )

                logger.info(f"Initializing Playwright browser for scraper: {self.config.name}")
                self.browser = await create_playwright_browser(
                    site_name=self.config.name,
                    headless=self.headless,
                    profile_suffix=profile_suffix,
                    timeout=self.timeout,
                )
            else:
                raise BrowserError("Unsupported browser backend.")

            logger.info(f"Browser initialized for scraper: {self.config.name} (Backend: {backend})")

        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise BrowserError(
                f"Failed to initialize browser: {e}",
                context=ErrorContext(site_name=self.config.name),
            )

        # Initialize anti-detection manager if configured
        if self.config.anti_detection:
            try:
                self.anti_detection_manager = AntiDetectionManager(self.browser, self.config.anti_detection, self.config.name)
                logger.info(f"Anti-detection manager initialized for scraper: {self.config.name}")
            except Exception as e:
                logger.warning(f"Failed to initialize anti-detection manager: {e}")
                self.anti_detection_manager = None

        # Initialize extracted modules
        self._init_extracted_modules()

    def _init_extracted_modules(self) -> None:
        """Initialize all extracted module instances."""
        # Selector resolver (for element finding and value extraction)
        self.selector_resolver = SelectorResolver(self.browser)

        # Debug artifact capture
        self.debug_capture = DebugArtifactCapture(
            job_id=self.job_id,
            scraper_name=self.config.name,
            debug_mode=self.debug_mode,
            debug_callback=self.debug_callback,
        )

        # Normalization engine
        self.normalization_engine = NormalizationEngine()

        # Step executor - pass self as context for action ScraperContext protocol
        self.step_executor = StepExecutor(
            config_name=self.config.name,
            browser=self.browser,
            retry_executor=self.retry_executor,
            enable_retry=self.enable_retry,
            max_retries=self.max_retries,
            stop_event=self.stop_event,
            debug_mode=self.debug_mode,
            debug_callback=self.debug_callback,
            context=self,
            event_emitter=self.event_emitter,
        )

    async def dispatch_step(self, step: WorkflowStep) -> Any:
        """Dispatch a workflow step for execution. Used by actions."""
        return await self._execute_step(step, self.context)

    def _register_recovery_handlers(self) -> None:
        """Register recovery handlers for different failure types."""
        import asyncio

        # CAPTCHA recovery handler
        async def handle_captcha(context: ErrorContext) -> bool:
            """Attempt to handle CAPTCHA detection."""
            logger.info("Attempting CAPTCHA recovery...")
            # For now, just wait and hope it resolves
            # In the future, integrate with CAPTCHA solving service
            await asyncio.sleep(5)
            # Try refreshing the page
            try:
                self.browser.page.reload()
                await asyncio.sleep(2)
                return True
            except Exception as e:
                logger.warning(f"CAPTCHA recovery failed: {e}")
                return False

        # Rate limit recovery handler
        async def handle_rate_limit(context: ErrorContext) -> bool:
            """Handle rate limiting by waiting."""
            logger.info("Handling rate limit - waiting 30 seconds...")
            await asyncio.sleep(30)
            return True

        # Access denied recovery handler
        async def handle_access_denied(context: ErrorContext) -> bool:
            """Handle access denied by rotating session."""
            logger.info("Attempting session rotation for access denied...")
            if self.anti_detection_manager:
                try:
                    # Clear cookies and rotate user agent
                    self.browser.context.clear_cookies()
                    await asyncio.sleep(2)
                    return True
                except Exception as e:
                    logger.warning(f"Session rotation failed: {e}")
            return False

        # Register handlers
        self.retry_executor.register_recovery_handler(FailureType.CAPTCHA_DETECTED, handle_captcha)
        self.retry_executor.register_recovery_handler(FailureType.RATE_LIMITED, handle_rate_limit)
        self.retry_executor.register_recovery_handler(FailureType.ACCESS_DENIED, handle_access_denied)

    async def execute_workflow(self, context: dict[str, Any] | None = None, quit_browser: bool = True) -> dict[str, Any]:
        """
        Execute the complete workflow defined in the configuration.

        Args:
            context: Dictionary of context variables (e.g. {'sku': '123'})
            quit_browser: Whether to quit the browser after execution

        Returns:
            Dict containing execution results and extracted data

        Raises:
            WorkflowExecutionError: If workflow execution fails critically
        """
        try:
            total_steps = len(self.config.workflows)
            logger.info(f"Starting workflow execution for: {self.config.name} ({total_steps} steps)")

            if total_steps == 0:
                logger.warning(f"No workflow steps defined for {self.config.name} - config may be incomplete")

            self.results = {}  # Reset results for new run
            self.workflow_stopped = False  # Reset stop flag for new run
            self.step_errors = []  # Reset error tracking
            self.current_step_index = 0

            # Check for cancellation at start
            if self.stop_event and self.stop_event.is_set():
                logger.warning(f"Workflow execution cancelled before starting for: {self.config.name}")
                raise WorkflowExecutionError("Workflow cancelled", context=ErrorContext(site_name=self.config.name))

            # Merge context into results so they are available
            if context:
                self.context = context  # Update instance context
                self.results.update(context)
                logger.debug(f"Workflow context: {context}")

            for i, step in enumerate(self.config.workflows, 1):
                self.current_step_index = i

                if self.workflow_stopped:
                    logger.info("Workflow stopped due to condition, skipping remaining steps.")
                    break

                logger.info(f"Step {i}/{total_steps}: Executing {step.action}")
                logger.debug(f"Step {i} params: {step.params}")

                try:
                    await self._execute_step_with_retry(step, context, step_index=i)
                    logger.info(f"Step {i}/{total_steps}: Completed {step.action}")
                except NonRetryableError as e:
                    # Non-retryable errors for specific SKUs should not stop the workflow
                    if isinstance(e, CircuitBreakerOpenError):
                        logger.error(f"Circuit breaker open for {self.config.name}: {e}")
                        self.step_errors.append(
                            {
                                "step": i,
                                "action": step.action,
                                "error_type": "CircuitBreakerOpen",
                                "message": str(e),
                                "recoverable": False,
                            }
                        )
                        raise WorkflowExecutionError(f"Circuit breaker open: {e}")
                    elif isinstance(e, (NoResultsError, PageNotFoundError)):
                        logger.info(f"Step {i}: {type(e).__name__} - {e.message}")
                        self.step_errors.append(
                            {
                                "step": i,
                                "action": step.action,
                                "error_type": type(e).__name__,
                                "message": e.message,
                                "recoverable": False,
                            }
                        )
                        # Continue to next step or stop workflow gracefully
                        self.workflow_stopped = True
                        break
                    raise

            logger.info(f"Workflow execution completed for: {self.config.name}")

            # Apply normalization rules
            self.apply_normalization()

            return {
                "success": True,
                "results": self.results,
                "config_name": self.config.name,
                "steps_executed": self.current_step_index,
                "total_steps": total_steps,
                "errors": self.step_errors,
                "image_quality": self.config.image_quality,
            }

        except WorkflowExecutionError:
            raise
        except ScraperError as e:
            logger.error(f"Workflow execution failed with scraper error: {e}")
            raise WorkflowExecutionError(str(e), context=e.context, cause=e)
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise WorkflowExecutionError(
                f"Workflow execution failed: {e}",
                context=ErrorContext(site_name=self.config.name),
            )
        finally:
            if quit_browser and self.browser:
                self.browser.quit()

    async def execute_steps(self, steps: list[Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute specific workflow steps.

        Args:
            steps: List of WorkflowStep objects to execute
            context: Dictionary of context variables

        Returns:
            Dict containing execution results and extracted data

        Raises:
            WorkflowExecutionError: If step execution fails
        """
        try:
            logger.info(f"Starting step execution for: {self.config.name}")

            for i, step in enumerate(steps, 1):
                if self.workflow_stopped:
                    logger.info("Workflow stopped due to condition, skipping remaining steps.")
                    break
                await self._execute_step_with_retry(step, context, step_index=i)

            logger.info(f"Step execution completed for: {self.config.name}")
            return {
                "success": True,
                "results": self.results,
                "config_name": self.config.name,
                "steps_executed": len(steps),
            }

        except Exception as e:
            logger.error(f"Step execution failed: {e}")
            raise WorkflowExecutionError(
                f"Step execution failed: {e}",
                context=ErrorContext(site_name=self.config.name),
            )

    async def _execute_step_with_retry(
        self,
        step: WorkflowStep,
        context: dict[str, Any] | None = None,
        step_index: int = 0,
    ) -> None:
        """Execute a workflow step with retry logic. Delegates to StepExecutor."""
        await self.step_executor.execute_step_with_retry(step, context, step_index)

    async def _execute_step(self, step: WorkflowStep, context: dict[str, Any] | None = None) -> Any:
        """Execute a single workflow step. Delegates to StepExecutor."""
        return await self.step_executor.execute_step(step, context or {}, self.results)

    # _get_locator_type removed

    async def find_element_safe(self, selector: str, required: bool = True, timeout: int | None = None) -> Any:
        """Find a single element using Playwright. Delegates to SelectorResolver."""
        return await self.selector_resolver.find_element_safe(selector, required, timeout)

    async def find_elements_safe(self, selector: str, timeout: int | None = None) -> list[Any]:
        """Find multiple elements using Playwright. Delegates to SelectorResolver."""
        return await self.selector_resolver.find_elements_safe(selector, timeout)

    async def extract_value_from_element(self, element: Any, attribute: str | None = None) -> Any:
        """Extract value from element (text, attribute, etc.). Delegates to SelectorResolver."""
        return await self.selector_resolver.extract_value_from_element(element, attribute)

    def _extract_value_from_element(self, element: Any, attribute: str | None = None) -> Any:
        """Private alias for backward compatibility with existing actions."""
        return self.extract_value_from_element(element, attribute)

    def get_results(self) -> dict[str, Any]:
        """Get the current execution results."""
        return self.results.copy()

    def resolve_selector(self, identifier: str) -> SelectorConfig | None:
        """
        Resolve a selector by ID first, then by name as fallback.

        Args:
            identifier: Either a selector ID (e.g., 'sel_abc123') or a selector name

        Returns:
            SelectorConfig if found, None otherwise
        """
        # 1. Try direct ID lookup first (preferred)
        selector = self.selectors_by_id.get(identifier)
        if selector:
            return selector

        # 2. Fallback to name-based lookup
        selector = self.selectors.get(identifier)
        if selector:
            # Log usage of name-based lookup if we have IDs available (indicates old config format)
            if self.selectors_by_id:
                logger.debug(f"Using name-based selector lookup for '{identifier}'. Consider migrating to ID-based references.")
            return selector

        return None

    def is_session_authenticated(self) -> bool:
        """
        Check if the current session is authenticated and not expired.

        Returns:
            True if session is authenticated and valid, False otherwise
        """
        if not self.session_authenticated:
            return False

        if self.session_auth_time is None:
            return False

        # Check if session has expired
        elapsed = time.time() - self.session_auth_time
        if elapsed > self.session_timeout:
            logger.info(f"Session expired after {elapsed:.1f}s (timeout: {self.session_timeout}s)")
            self.session_authenticated = False
            self.session_auth_time = None
            return False

        return True

    def mark_session_authenticated(self) -> None:
        """Mark the current session as authenticated."""
        self.session_authenticated = True
        self.session_auth_time = time.time()
        logger.info(f"Session marked as authenticated for scraper: {self.config.name}")

    def reset_session(self) -> None:
        """Reset the authentication session."""
        self.session_authenticated = False
        self.session_auth_time = None
        logger.info(f"Session reset for scraper: {self.config.name}")

    def get_session_status(self) -> dict[str, Any]:
        """Get current session status information."""
        return {
            "authenticated": self.session_authenticated,
            "auth_time": self.session_auth_time,
            "elapsed": time.time() - self.session_auth_time if self.session_auth_time else None,
            "timeout": self.session_timeout,
            "expired": not self.is_session_authenticated() if self.session_authenticated else False,
        }

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get the current circuit breaker status for this scraper."""
        return self.retry_executor.get_circuit_breaker_status(self.config.name)

    def reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker for this scraper."""
        self.retry_executor.reset_circuit_breaker(self.config.name)

    def apply_normalization(self) -> None:
        """Apply normalization rules to extracted results. Delegates to NormalizationEngine."""
        if not self.config.normalization:
            return

        # Convert NormalizationRule objects to dicts for the engine
        rule_dicts = []
        for rule in self.config.normalization:
            rule_dicts.append(
                {
                    "field": rule.field,
                    "action": rule.action,
                    "params": rule.params,
                }
            )

        self.normalization_engine.normalize_results(self.results, rule_dicts)

    async def _capture_debug_on_failure(
        self,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Capture debug artifacts on failure. Delegates to DebugArtifactCapture."""
        page = self.browser.page if hasattr(self.browser, "page") else None
        await self.debug_capture.capture_debug_state(
            step_name=action,
            page=page,
            context=context,
            error=None,
        )
