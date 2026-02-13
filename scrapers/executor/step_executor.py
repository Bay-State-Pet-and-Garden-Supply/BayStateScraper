"""
Step executor for workflow step execution with retry logic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.events import EventEmitter
from core.retry_executor import RetryExecutor
from scrapers.actions import ActionRegistry
from scrapers.exceptions import ConfigurationError, ErrorContext
from scrapers.models.config import WorkflowStep

logger = logging.getLogger(__name__)


class StepExecutor:
    """Executes individual workflow steps with retry logic and action dispatch."""

    def __init__(
        self,
        config_name: str,
        browser: Any,
        retry_executor: RetryExecutor,
        enable_retry: bool = True,
        max_retries: int = 3,
        stop_event: Any | None = None,
        debug_mode: bool = False,
        debug_callback: Any | None = None,
        context: Any | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        """
        Initialize the step executor.

        Args:
            config_name: Name of the scraper configuration
            browser: Browser instance for action execution
            retry_executor: RetryExecutor instance for retry logic
            enable_retry: Whether to enable retry logic
            max_retries: Maximum number of retry attempts
            stop_event: Optional threading.Event to check for cancellation
            debug_mode: Whether to enable debug mode
            debug_callback: Optional callback for debug artifacts
            context: The WorkflowExecutor instance to pass to actions (for ScraperContext protocol)
            event_emitter: Optional EventEmitter for v2 event emission
        """
        self.config_name = config_name
        self.browser = browser
        self.retry_executor = retry_executor
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.stop_event = stop_event
        self.debug_mode = debug_mode
        self.debug_callback = debug_callback
        self.context = context
        self.event_emitter = event_emitter
        self._step_selector_results: dict[str, Any] = {}
        self._step_extraction_results: dict[str, Any] = {}

    async def execute_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
        results: dict[str, Any],
    ) -> Any:
        """
        Execute a single workflow step with retry and error handling.

        Args:
            step: WorkflowStep to execute
            context: Context variables for substitution
            results: Results dictionary for storing output

        Returns:
            Result of the action execution

        Raises:
            ConfigurationError: If action is not registered
            ScraperError: If step execution fails
        """
        # Substitute variables in step parameters
        substituted_params = self._substitute_params(step.params, context)

        # Get action class from registry
        action_class = ActionRegistry.get_action_class(step.action)
        if not action_class:
            raise ConfigurationError(
                f"Unknown action: {step.action}",
                context=ErrorContext(site_name=self.config_name, action=step.action),
            )

        # Instantiate action with scraper context (WorkflowExecutor)
        action_instance = action_class(self.context if self.context else self)

        try:
            # Execute the action (support both sync and async actions)
            import inspect

            result = action_instance.execute(substituted_params)
            if inspect.isawaitable(result):
                result = await result

            # Capture debug artifacts on success if in debug mode
            if self.debug_mode and self.debug_callback:
                await self._capture_debug_artifact(step.action, context, success=True)

            return result

        except Exception:
            # Capture debug artifacts on failure
            await self._capture_debug_artifact(step.action, context, success=False)
            raise

    async def execute_step_with_retry(
        self,
        step: WorkflowStep,
        context: dict[str, Any] | None = None,
        step_index: int = 0,
    ) -> Any:
        """
        Execute a workflow step with retry logic.

        Args:
            step: WorkflowStep to execute
            context: Context variables for substitution
            step_index: Index of the step in the workflow

        Returns:
            Result of the action execution

        Raises:
            MaxRetriesExceededError: If all retry attempts fail
            NonRetryableError: If error cannot be retried
        """
        from scrapers.exceptions import (
            CircuitBreakerOpenError,
            MaxRetriesExceededError,
            NonRetryableError,
            WorkflowExecutionError,
        )

        sku = context.get("sku") if context else None
        started_at = datetime.now().isoformat()

        # Emit step.started event (v2)
        if self.event_emitter:
            self.event_emitter.step_started(
                scraper=self.config_name,
                step_index=step_index,
                action=step.action,
                name=step.params.get("name"),
                sku=sku,
            )

        # Reset per-step tracking
        self._step_selector_results = {}
        self._step_extraction_results = {}

        # Build error context
        error_context = ErrorContext(
            site_name=self.config_name,
            action=step.action,
            step_index=step_index,
            sku=sku,
            max_retries=self.max_retries,
        )

        # Determine if this step should use retry logic
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

        try:
            if should_retry:
                # Use retry executor
                result = await self.retry_executor.execute_with_retry(
                    operation=lambda: self.execute_step(step, context or {}, {}),
                    site_name=self.config_name,
                    action_name=step.action,
                    context=error_context,
                    max_retries=self.max_retries,
                    on_retry=self._on_retry_callback,
                    stop_event=self.stop_event,
                )

                if not result.success:
                    # Check if cancelled
                    if result.cancelled:
                        raise NonRetryableError("Operation cancelled", context=error_context)

                    # Re-raise the error
                    if result.error:
                        raise result.error
                    raise WorkflowExecutionError(
                        f"Step '{step.action}' failed after {result.attempts} attempts",
                        context=error_context,
                    )

                # Emit step.completed event (v2) with timing and metadata
                if self.event_emitter:
                    self.event_emitter.step_completed(
                        scraper=self.config_name,
                        step_index=step_index,
                        action=step.action,
                        started_at=started_at,
                        name=step.params.get("name"),
                        sku=sku,
                        selectors=self._step_selector_results if self._step_selector_results else None,
                        extraction=self._step_extraction_results if self._step_extraction_results else None,
                        retry_count=result.attempts - 1,
                        max_retries=self.max_retries,
                    )

                return result.result
            else:
                # Execute without retry
                result = await self.execute_step(step, context or {}, {})

                # Emit step.completed event (v2) with timing and metadata
                if self.event_emitter:
                    self.event_emitter.step_completed(
                        scraper=self.config_name,
                        step_index=step_index,
                        action=step.action,
                        started_at=started_at,
                        name=step.params.get("name"),
                        sku=sku,
                        selectors=self._step_selector_results if self._step_selector_results else None,
                        extraction=self._step_extraction_results if self._step_extraction_results else None,
                        retry_count=0,
                        max_retries=self.max_retries,
                    )

                return result

        except Exception as e:
            # Emit step.failed event (v2) with timing and error details
            if self.event_emitter:
                retryable = not isinstance(e, (NonRetryableError, CircuitBreakerOpenError))
                self.event_emitter.step_failed(
                    scraper=self.config_name,
                    step_index=step_index,
                    action=step.action,
                    started_at=started_at,
                    error=str(e),
                    name=step.params.get("name"),
                    sku=sku,
                    retry_count=0,
                    max_retries=self.max_retries,
                    retryable=retryable,
                )
            raise

    def _substitute_params(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Substitute variables in step parameters using context.

        Args:
            params: Original step parameters
            context: Context variables for substitution

        Returns:
            Parameters with variables substituted
        """
        substituted: dict[str, Any] = {}

        for key, value in params.items():
            if isinstance(value, str):
                substituted[key] = self._substitute_variables(value, context)
            elif isinstance(value, dict):
                # Recursively substitute in nested dicts
                substituted[key] = {k: self._substitute_variables(v, context) if isinstance(v, str) else v for k, v in value.items()}
            else:
                substituted[key] = value

        return substituted

    def _substitute_variables(self, text: str, context: dict[str, Any]) -> str:
        """
        Substitute variables in text using context.

        Args:
            text: Text containing potential placeholders
            context: Context variables for substitution

        Returns:
            Text with variables substituted
        """
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

    def _on_retry_callback(self, attempt: int, error: Exception, delay: float) -> None:
        """Callback called before each retry attempt."""
        logger.info(f"Retry attempt {attempt + 2} for {self.config_name} after {type(error).__name__}, waiting {delay:.2f}s")

    async def _capture_debug_artifact(
        self,
        action: str,
        context: dict[str, Any] | None,
        success: bool,
    ) -> None:
        """
        Capture debug artifacts (page source, screenshot).

        Args:
            action: Name of the action being executed
            context: Context variables
            success: Whether the action succeeded
        """
        if not self.debug_mode or not self.debug_callback:
            return

        try:
            sku = context.get("sku") if context else None
            debug_data = {
                "scraper": self.config_name,
                "step": action,
                "sku": sku,
                "success": success,
            }

            # Get page source if available
            if hasattr(self.browser, "page"):
                try:
                    debug_data["page_source"] = self.browser.page.content()
                except Exception as e:
                    logger.debug(f"Failed to capture page source: {e}")

                # Get URL if available
                try:
                    debug_data["url"] = self.browser.page.url
                except Exception:
                    pass

            self.debug_callback(debug_data)

        except Exception as e:
            logger.debug(f"Failed to capture debug artifact: {e}")

    def track_selector_result(
        self,
        name: str,
        selector: str,
        found: bool,
        count: int = 0,
        attribute: str | None = None,
        error: str | None = None,
    ) -> None:
        """Track selector resolution result for v2 events."""
        self._step_selector_results[name] = {
            "value": selector,
            "found": found,
            "count": count,
        }
        if attribute:
            self._step_selector_results[name]["attribute"] = attribute
        if error:
            self._step_selector_results[name]["error"] = error

        # Also emit immediate selector.resolved event (v2)
        if self.event_emitter:
            sku = None
            if self.context and hasattr(self.context, "results"):
                sku = self.context.results.get("sku")
            self.event_emitter.selector_resolved(
                scraper=self.config_name,
                selector_name=name,
                selector_value=selector,
                found=found,
                count=count,
                attribute=attribute,
                error=error,
                sku=sku,
            )

    def track_extraction_result(
        self,
        field_name: str,
        value: Any,
        status: str = "SUCCESS",
        confidence: float = 1.0,
        error: str | None = None,
    ) -> None:
        """Track extraction result for v2 events."""
        self._step_extraction_results[field_name] = {
            "value": value,
            "status": status,
            "confidence": confidence,
        }
        if error:
            self._step_extraction_results[field_name]["error"] = error

        # Also emit immediate extraction.completed event (v2)
        if self.event_emitter:
            sku = None
            if self.context and hasattr(self.context, "results"):
                sku = self.context.results.get("sku")
            self.event_emitter.extraction_completed(
                scraper=self.config_name,
                field_name=field_name,
                value=value,
                status=status,
                confidence=confidence,
                error=error,
                sku=sku,
            )
