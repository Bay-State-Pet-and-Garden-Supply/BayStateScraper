"""
Workflow executor for scraper automation using Selenium WebDriver.
"""

import logging
import os
import re
import threading
import time
from typing import Any

# Selenium imports removed
# from selenium.webdriver.common.by import By
from scraper_backend.core.adaptive_retry_strategy import AdaptiveRetryStrategy
from scraper_backend.core.anti_detection_manager import AntiDetectionManager
from scraper_backend.core.failure_analytics import FailureAnalytics
from scraper_backend.core.failure_classifier import FailureClassifier, FailureType
from scraper_backend.core.retry_executor import CircuitBreakerConfig, RetryExecutor, RetryResult
from scraper_backend.core.settings_manager import PROJECT_ROOT, SettingsManager
from scraper_backend.scrapers.actions import ActionRegistry
from scraper_backend.scrapers.exceptions import (
    BrowserError,
    CircuitBreakerOpenError,
    ErrorContext,
    MaxRetriesExceededError,
    NonRetryableError,
    NoResultsError,
    PageNotFoundError,
    ScraperError,
    WorkflowExecutionError,
)
from scraper_backend.scrapers.models.config import ScraperConfig, SelectorConfig, WorkflowStep
from scraper_backend.utils.scraping.playwright_browser import (
    SyncPlaywrightScraperBrowser as ScraperBrowser,
)
from scraper_backend.utils.scraping.playwright_browser import (
    create_sync_playwright_browser as create_browser,
)

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """
    Executes scraper workflows defined in YAML configurations using Selenium WebDriver.

    Supports actions like navigate, wait_for, extract_single, extract_multiple, input_text, click.
    Includes comprehensive error handling, intelligent retry logic, and result collection.
    """

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

        self.browser: Any  # Union[ScraperBrowser, SyncPlaywrightScraperBrowser]
        self.results: dict[str, Any] = {}
        self.context: dict[str, Any] = {}  # Store execution context

        # Build selector lookup dictionaries (ID-based primary, name-based fallback)
        self.selectors_by_id: dict[str, SelectorConfig] = {
            s.id: s for s in config.selectors if s.id
        }
        self.selectors: dict[str, SelectorConfig] = {s.name: s for s in config.selectors}

        self.anti_detection_manager: AntiDetectionManager | None = None

        # Initialize adaptive retry strategy with history persistence
        history_path = os.path.join(PROJECT_ROOT, "data", f"retry_history_{config.name}.json")
        self.adaptive_retry_strategy = AdaptiveRetryStrategy(history_file=history_path)

        # Initialize failure classifier with site-specific patterns
        no_results_selectors = (
            self.config.validation.no_results_selectors if self.config.validation else []
        )
        no_results_text_patterns = (
            self.config.validation.no_results_text_patterns if self.config.validation else []
        )
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

        # Initialize browser
        try:
            import uuid

            # Use random UUID for profile path to ensure isolation (Old Setup)
            # This prevents locking issues at the cost of no persistence
            profile_suffix = f"workflow_{int(time.time())}_{uuid.uuid4().hex[:8]}"

            backend = "playwright"  # Force Playwright since Selenium is removed
            # self.settings.get("browser_backend", "playwright")

            if backend == "playwright":
                from scraper_backend.utils.scraping.playwright_browser import (
                    create_sync_playwright_browser,
                )

                logger.info(f"Initializing Playwright browser for scraper: {self.config.name}")
                self.browser = create_sync_playwright_browser(
                    site_name=self.config.name,
                    headless=headless,
                    profile_suffix=profile_suffix,
                    timeout=self.timeout,
                )
            else:
                raise BrowserError(
                    "Selenium backend is no longer supported. Please use Playwright."
                )

            logger.info(f"Browser initialized for scraper: {self.config.name} (Backend: {backend})")

            # Log browser capabilities for debugging (Selenium only)
            # Capabilities logging removed (Selenium specific)

        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise BrowserError(
                f"Failed to initialize browser: {e}",
                context=ErrorContext(site_name=config.name),
            )

        # Initialize anti-detection manager if configured
        if config.anti_detection:
            try:
                self.anti_detection_manager = AntiDetectionManager(
                    self.browser, config.anti_detection, config.name
                )
                logger.info(f"Anti-detection manager initialized for scraper: {self.config.name}")
            except Exception as e:
                logger.warning(f"Failed to initialize anti-detection manager: {e}")
                self.anti_detection_manager = None

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

    def _register_recovery_handlers(self) -> None:
        """Register recovery handlers for different failure types."""

        # CAPTCHA recovery handler
        def handle_captcha(context: ErrorContext) -> bool:
            """Attempt to handle CAPTCHA detection."""
            logger.info("Attempting CAPTCHA recovery...")
            # For now, just wait and hope it resolves
            # In the future, integrate with CAPTCHA solving service
            time.sleep(5)
            # Try refreshing the page
            try:
                self.browser.driver.refresh()  # type: ignore
                time.sleep(2)
                return True
            except Exception as e:
                logger.warning(f"CAPTCHA recovery failed: {e}")
                return False

        # Rate limit recovery handler
        def handle_rate_limit(context: ErrorContext) -> bool:
            """Handle rate limiting by waiting."""
            logger.info("Handling rate limit - waiting 30 seconds...")
            time.sleep(30)
            return True

        # Access denied recovery handler
        def handle_access_denied(context: ErrorContext) -> bool:
            """Handle access denied by rotating session."""
            logger.info("Attempting session rotation for access denied...")
            if self.anti_detection_manager:
                try:
                    # Clear cookies and rotate user agent
                    self.browser.driver.delete_all_cookies()  # type: ignore
                    time.sleep(2)
                    return True
                except Exception as e:
                    logger.warning(f"Session rotation failed: {e}")
            return False

        # Register handlers
        self.retry_executor.register_recovery_handler(FailureType.CAPTCHA_DETECTED, handle_captcha)
        self.retry_executor.register_recovery_handler(FailureType.RATE_LIMITED, handle_rate_limit)
        self.retry_executor.register_recovery_handler(
            FailureType.ACCESS_DENIED, handle_access_denied
        )

    def execute_workflow(
        self, context: dict[str, Any] | None = None, quit_browser: bool = True
    ) -> dict[str, Any]:
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
            logger.info(f"Starting workflow execution for: {self.config.name}")
            self.results = {}  # Reset results for new run
            self.workflow_stopped = False  # Reset stop flag for new run
            self.step_errors = []  # Reset error tracking
            self.current_step_index = 0

            # Check for cancellation at start
            if self.stop_event and self.stop_event.is_set():
                logger.warning(
                    f"Workflow execution cancelled before starting for: {self.config.name}"
                )
                raise WorkflowExecutionError(
                    "Workflow cancelled", context=ErrorContext(site_name=self.config.name)
                )

            # Merge context into results so they are available
            if context:
                self.context = context  # Update instance context
                self.results.update(context)

            total_steps = len(self.config.workflows)
            for i, step in enumerate(self.config.workflows, 1):
                self.current_step_index = i

                if self.workflow_stopped:
                    logger.info("Workflow stopped due to condition, skipping remaining steps.")
                    break

                logger.info(f"Step {i}/{total_steps}: Executing {step.action}")

                try:
                    self._execute_step_with_retry(step, context, step_index=i)
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

    def execute_steps(
        self, steps: list[Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
                self._execute_step_with_retry(step, context, step_index=i)

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

    def _substitute_variables(self, text: str, context: dict[str, Any]) -> str:
        """Substitute variables in text using context."""
        if not context or not isinstance(text, str):
            return text

        try:
            # Only format if it looks like it has placeholders
            if "{" in text and "}" in text:
                return text.format(**context)
        except Exception:
            # If formatting fails (e.g. missing key), return original
            pass
        return text

    def _execute_step_with_retry(
        self,
        step: WorkflowStep,
        context: dict[str, Any] | None = None,
        step_index: int = 0,
    ) -> None:
        """
        Execute a workflow step with retry logic.

        Args:
            step: WorkflowStep to execute
            context: Context variables for substitution
            step_index: Index of the step in the workflow
        """
        # Build error context
        error_context = ErrorContext(
            site_name=self.config.name,
            action=step.action,
            step_index=step_index,
            sku=context.get("sku") if context else None,
            max_retries=self.max_retries,
        )

        # Determine if this step should use retry logic
        # Some actions like extract don't benefit from retry
        retryable_actions = {
            "navigate",
            "wait_for",
            "click",
            "input_text",
            "login",
            "check_no_results",
            "detect_captcha",
        }
        should_retry = self.enable_retry and step.action in retryable_actions

        if should_retry:
            # Use retry executor
            result = self.retry_executor.execute_with_retry(
                operation=lambda: self._execute_step(step, context),
                site_name=self.config.name,
                action_name=step.action,
                context=error_context,
                max_retries=self.max_retries,
                on_retry=self._on_retry_callback,
                stop_event=self.stop_event,
            )

            if not result.success:
                # Check if cancelled
                if result.cancelled:
                    from scraper_backend.scrapers.exceptions import NonRetryableError

                    raise NonRetryableError("Operation cancelled", context=error_context)

                # Track the error
                self.step_errors.append(
                    {
                        "step": step_index,
                        "action": step.action,
                        "error_type": type(result.error).__name__ if result.error else "Unknown",
                        "message": str(result.error) if result.error else "Unknown error",
                        "attempts": result.attempts,
                        "total_delay": result.total_delay,
                    }
                )

                # Re-raise the error
                if result.error:
                    raise result.error
                raise WorkflowExecutionError(
                    f"Step '{step.action}' failed after {result.attempts} attempts",
                    context=error_context,
                )
        else:
            # Execute without retry
            try:
                self._execute_step(step, context)
            except Exception as e:
                self.step_errors.append(
                    {
                        "step": step_index,
                        "action": step.action,
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "attempts": 1,
                    }
                )
                raise

    def _on_retry_callback(self, attempt: int, error: Exception, delay: float) -> None:
        """Callback called before each retry attempt."""
        logger.info(
            f"Retry attempt {attempt + 2} for {self.config.name} after "
            f"{type(error).__name__}, waiting {delay:.2f}s"
        )

    def _execute_step(self, step: WorkflowStep, context: dict[str, Any] | None = None) -> None:
        """
        Execute a single workflow step using the action registry.

        Args:
            step: WorkflowStep to execute
            context: Context variables for substitution
        """
        # Substitute variables in step parameters
        substituted_params: dict[str, Any] = {}
        for key, value in step.params.items():
            if isinstance(value, str):
                substituted_params[key] = self._substitute_variables(value, context or {})
            elif isinstance(value, dict):
                # Recursively substitute in nested dicts
                substituted_params[key] = {
                    k: self._substitute_variables(v, context or {}) if isinstance(v, str) else v
                    for k, v in value.items()
                }
            else:
                substituted_params[key] = value

        # Get action class from registry
        action_class = ActionRegistry.get_action_class(step.action)
        if not action_class:
            from scraper_backend.scrapers.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Unknown action: {step.action}",
                context=ErrorContext(site_name=self.config.name, action=step.action),
            )

        # Instantiate and execute action
        action_instance = action_class(self)
        try:
            action_instance.execute(substituted_params)
            # DEBUG: Dump source after every step (only in debug mode)
            # DEBUG: capture state after every step (only in debug mode)
            if self.debug_mode and self.debug_callback:
                try:
                    # Capture source
                    src = self.browser.driver.page_source
                    
                    # Also capture screenshot if important step? For now just source to reduce I/O
                    # Actually, user wants "page-source" endpoint to work.
                    
                    self.debug_callback({
                        "scraper": self.config.name,
                        "step": step.action,
                        "page_source": src
                    })
                except Exception as e:
                    logger.debug(f"Failed to capture success debug artifact: {e}")
        except Exception:
            # Capture debug artifacts on failure
            self._capture_debug_on_failure(step.action, context)

            # Re-raise with context
            raise

    # _get_locator_type removed

    def find_element_safe(self, selector: str):
        """
        Find a single element using Playwright.
        """
        try:
            # Handle XPath explicitly for Playwright if needed
            if selector.startswith("//") or selector.startswith(".//"):
                if not selector.startswith("xpath="):
                    selector = f"xpath={selector}"

            if hasattr(self.browser, "page"):
                return self.browser.page.query_selector(selector)
            return None
        except Exception:
            return None

    def find_elements_safe(self, selector: str):
        """
        Find multiple elements using Playwright.
        """
        try:
            # Handle XPath explicitly for Playwright
            if selector.startswith("//") or selector.startswith(".//"):
                if not selector.startswith("xpath="):
                    selector = f"xpath={selector}"

            if hasattr(self.browser, "page"):
                return self.browser.page.query_selector_all(selector)
            return []
        except Exception:
            return []

    def _extract_value_from_element(self, element, attribute: str | None) -> str | None:
        """
        Extract value from a web element based on attribute.

        Args:
            element: Selenium WebElement or Playwright ElementHandle
            attribute: Attribute to extract ('text', 'href', 'src', etc.) or None for text

        Returns:
            Extracted value or None
        """
        try:
            # Determine backend based on element type
            is_playwright_element = hasattr(element, "inner_text") or (
                hasattr(element, "get_attribute") and not hasattr(element, "tag_name")
            )

            if attribute == "text" or attribute is None:
                if is_playwright_element:
                    # Playwright text extraction
                    text = element.inner_text().strip() if element.inner_text() else ""
                    if not text:
                        text_content = element.text_content()
                        text = text_content.strip() if text_content else ""
                else:
                    # Selenium text extraction
                    text = element.text.strip() if element.text else ""
                    # Fallback to textContent if .text is empty (handles JS-rendered content)
                    if not text:
                        text_content = element.get_attribute("textContent")
                        text = text_content.strip() if text_content else ""
                return text if text else None

            elif attribute in ["href", "src", "alt", "title", "value"]:
                attr_value = element.get_attribute(attribute)
                if attr_value is not None:
                    # For URL attributes, resolve relative URLs to absolute
                    if attribute in ["href", "src"] and attr_value.startswith("/"):
                        # Use JavaScript to get the fully resolved URL property
                        try:
                            if is_playwright_element:
                                # Use evaluate to get the property value (not attribute)
                                resolved = element.evaluate(f"el => el.{attribute}")
                                if resolved:
                                    return str(resolved)
                            else:
                                # For Selenium, get_attribute usually returns resolved URLs
                                pass
                        except Exception:
                            pass  # Fall through to return the raw attribute
                    return str(attr_value)
                return None
            else:
                attr_value = element.get_attribute(attribute)
                return str(attr_value) if attr_value is not None else None
        except Exception as e:
            logger.warning(f"Failed to extract value from element: {e}")
            return None

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
                logger.debug(
                    f"Using name-based selector lookup for '{identifier}'. "
                    "Consider migrating to ID-based references."
                )
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

    def apply_normalization(self):
        """Apply normalization rules to extracted results."""
        if not self.config.normalization:
            return

        for rule in self.config.normalization:
            field = rule.field
            if field in self.results:
                value = self.results[field]
                if isinstance(value, str):
                    if rule.action == "title_case":
                        self.results[field] = value.title()
                    elif rule.action == "lowercase":
                        self.results[field] = value.lower()
                    elif rule.action == "uppercase":
                        self.results[field] = value.upper()
                    elif rule.action == "trim":
                        self.results[field] = value.strip()
                    elif rule.action == "remove_prefix":
                        prefix = rule.params.get("prefix", "")
                        if prefix and value.startswith(prefix):
                            self.results[field] = value[len(prefix) :].strip()
                    elif rule.action == "extract_weight":
                        # Extract number and unit, convert to lbs
                        # Match number (int or float) followed by optional unit
                        # Handles: "5 lbs", "5.5kg", "Weight: 10 oz", etc.
                        match = re.search(
                            r"(\d+(?:\.\d+)?)\s*(lbs?|lb|oz|kg|g)?", value, re.IGNORECASE
                        )
                        if match:
                            weight = float(match.group(1))
                            unit = (match.group(2) or "lb").lower()

                            if unit in ["oz"]:
                                weight = weight / 16.0
                            elif unit in ["kg"]:
                                weight = weight * 2.20462
                            elif unit in ["g"]:
                                weight = weight * 0.00220462

                            # Format to 2 decimal places
                            self.results[field] = f"{weight:.2f}"

    def _capture_debug_on_failure(
        self,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Capture debug artifacts (page source, screenshot) on failure.

        Only captures if debug_mode is enabled and job_id is set.
        Falls back to local file dump if debug context is not available.
        """
        # Always dump to local file for backwards compatibility
        try:
            with open("debug_dump.html", "w", encoding="utf-8") as f:
                if hasattr(self.browser, "page"):
                    f.write(self.browser.page.content())
                elif hasattr(self.browser, "driver"):
                    f.write(self.browser.driver.page_source)
            logger.debug("Dumped page source to debug_dump.html")
        except Exception as dump_e:
            logger.debug(f"Failed to dump source to file: {dump_e}")

        # If debug mode is enabled, also capture to debug context
        if not self.debug_mode or not self.job_id:
            return

        try:
            from scraper_backend.api.debug_context import debug_context

            sku = context.get("sku") if context else None
            url = None
            page_source = None
            screenshot_bytes = None

            # Get current URL
            try:
                if hasattr(self.browser, "page"):
                    url = self.browser.page.url
                elif hasattr(self.browser, "driver"):
                    url = self.browser.driver.current_url
            except Exception:
                pass

            # Capture page source
            try:
                if hasattr(self.browser, "page"):
                    page_source = self.browser.page.content()
                elif hasattr(self.browser, "driver"):
                    page_source = self.browser.driver.page_source
            except Exception as e:
                logger.debug(f"Failed to capture page source: {e}")

            # Capture screenshot
            try:
                if hasattr(self.browser, "page"):
                    screenshot_bytes = self.browser.page.screenshot(type="png")
                elif hasattr(self.browser, "driver"):
                    screenshot_bytes = self.browser.driver.get_screenshot_as_png()
            except Exception as e:
                logger.debug(f"Failed to capture screenshot: {e}")

            # Store in debug context
            # Store in debug context via callback
            if self.debug_callback:
                import base64
                
                debug_data = {
                    "sku": sku,
                    "scraper": self.config.name,
                    "step": action,
                    "url": url,
                    "error": "Step failed"
                }

                if page_source:
                    debug_data["page_source"] = page_source
                
                if screenshot_bytes:
                    debug_data["screenshot"] = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                try:
                    self.debug_callback(debug_data)
                except Exception as ex:
                    logger.debug(f"Debug callback failed: {ex}")

            logger.debug(f"Captured debug artifacts for job {self.job_id}, step {action}")

        except Exception as e:
            logger.debug(f"Failed to capture debug artifacts: {e}")
