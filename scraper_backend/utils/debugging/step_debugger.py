"""
Step Debugger - execute workflow step-by-step with inspection.

Provides interactive debugging capabilities:
- Execute workflow one step at a time
- Inspect page state after each step
- Capture screenshots and page source
- View extracted data incrementally
- Skip/jump to specific steps
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class DebugState:
    """Current state of the debugger."""

    current_step: int = 0
    total_steps: int = 0
    url: str | None = None
    page_title: str | None = None
    page_source: str | None = None
    screenshot_base64: str | None = None
    extracted_data: dict[str, Any] = field(default_factory=dict)
    step_history: list["StepResult"] = field(default_factory=list)
    workflow_complete: bool = False
    workflow_stopped: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def summary(self) -> str:
        """Get a summary of current state."""
        lines = [
            f"Step: {self.current_step}/{self.total_steps}",
            f"URL: {self.url or 'N/A'}",
            f"Title: {self.page_title or 'N/A'}",
            f"Extracted fields: {len(self.extracted_data)}",
            f"Complete: {self.workflow_complete}",
        ]
        return "\n".join(lines)


@dataclass
class StepResult:
    """Result of executing a single step."""

    step_index: int
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: str | None = None
    timing_ms: float = 0.0
    extracted_data: dict[str, Any] = field(default_factory=dict)
    url_before: str | None = None
    url_after: str | None = None
    screenshot_base64: str | None = None
    page_source_preview: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        timing = f"({self.timing_ms:.1f}ms)"
        error_part = f" - {self.error}" if self.error else ""
        return f"Step {self.step_index}: {self.action} {status} {timing}{error_part}"


class StepDebugger:
    """
    Interactive step-by-step workflow debugger.

    Wraps WorkflowExecutor to provide granular control over
    workflow execution with state inspection capabilities.
    """

    def __init__(
        self,
        config_path: str | None = None,
        config_dict: dict[str, Any] | None = None,
        headless: bool = False,  # Default to visible for debugging
        timeout: int = 30,
        context: dict[str, Any] | None = None,
    ):
        """
        Initialize the step debugger.

        Args:
            config_path: Path to YAML config file
            config_dict: Config dictionary (alternative to config_path)
            headless: Run browser in headless mode
            timeout: Default timeout in seconds
            context: Initial context variables (e.g., {'sku': '123'})
        """
        self.config_path = config_path
        self.config_dict = config_dict
        self.headless = headless
        self.timeout = timeout
        self.context = context or {}

        self.executor: Any = None
        self.config: Any = None
        self.current_step_index = 0
        self.state = DebugState()
        self._initialized = False

    def _load_config(self) -> Any:
        """Load and parse the scraper configuration."""
        if self.config is not None:
            return self.config

        try:
            from scraper_backend.scrapers.parser.yaml_parser import ScraperConfigParser

            parser = ScraperConfigParser()

            if self.config_path:
                self.config = parser.load_from_file(self.config_path)
            elif self.config_dict:
                self.config = parser.load_from_dict(self.config_dict)
            else:
                raise ValueError("Either config_path or config_dict must be provided")

            return self.config

        except ImportError:
            # Fallback: load YAML directly without full parsing
            if self.config_path:
                with open(self.config_path, encoding="utf-8") as f:
                    self.config_dict = yaml.safe_load(f)
            raise

    def _ensure_executor(self) -> None:
        """Initialize the workflow executor if needed."""
        if self._initialized and self.executor:
            return

        config = self._load_config()

        try:
            from scraper_backend.scrapers.executor.workflow_executor import (
                WorkflowExecutor,
            )

            self.executor = WorkflowExecutor(
                config=config,
                headless=self.headless,
                timeout=self.timeout,
                enable_retry=False,  # Disable retry for debugging
                debug_mode=True,
            )

            # Update state
            self.state.total_steps = len(config.workflows)
            self.state.current_step = 0
            self._initialized = True

            logger.info(f"Step debugger initialized for: {config.name}")

        except ImportError as e:
            logger.error(f"Could not import WorkflowExecutor: {e}")
            raise

    def close(self) -> None:
        """Close the browser and cleanup."""
        if self.executor and hasattr(self.executor, "browser"):
            try:
                self.executor.browser.quit()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
        self.executor = None
        self._initialized = False

    def __enter__(self) -> "StepDebugger":
        self._ensure_executor()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def get_workflow_steps(self) -> list[dict[str, Any]]:
        """Get all workflow steps with their details."""
        config = self._load_config()

        steps = []
        for i, step in enumerate(config.workflows):
            steps.append(
                {
                    "index": i,
                    "action": step.action,
                    "params": step.params,
                }
            )
        return steps

    def step(self, capture_screenshot: bool = True) -> StepResult:
        """
        Execute the next workflow step.

        Args:
            capture_screenshot: Whether to capture screenshot after step

        Returns:
            StepResult with execution details
        """
        self._ensure_executor()

        if self.state.workflow_complete or self.state.workflow_stopped:
            return StepResult(
                step_index=self.current_step_index,
                action="(no more steps)",
                success=False,
                error="Workflow already complete or stopped",
            )

        config = self._load_config()

        if self.current_step_index >= len(config.workflows):
            self.state.workflow_complete = True
            return StepResult(
                step_index=self.current_step_index,
                action="(complete)",
                success=True,
            )

        step = config.workflows[self.current_step_index]

        # Get URL before step
        url_before = None
        try:
            if hasattr(self.executor, "browser") and hasattr(
                self.executor.browser, "page"
            ):
                url_before = self.executor.browser.page.url
        except Exception:
            pass

        # Execute step
        start_time = time.perf_counter()
        error = None
        success = True

        try:
            self.executor._execute_step(step, self.context)
        except Exception as e:
            error = str(e)
            success = False
            logger.warning(f"Step {self.current_step_index} failed: {e}")

        timing_ms = (time.perf_counter() - start_time) * 1000

        # Get URL after step
        url_after = None
        try:
            if hasattr(self.executor, "browser") and hasattr(
                self.executor.browser, "page"
            ):
                url_after = self.executor.browser.page.url
        except Exception:
            pass

        # Capture screenshot if requested
        screenshot = None
        if capture_screenshot:
            screenshot = self._capture_screenshot()

        # Get page source preview
        page_source_preview = None
        try:
            full_source = self._get_page_source()
            if full_source:
                page_source_preview = full_source[:2000]
        except Exception:
            pass

        # Build result
        result = StepResult(
            step_index=self.current_step_index,
            action=step.action,
            params=dict(step.params),
            success=success,
            error=error,
            timing_ms=timing_ms,
            extracted_data=dict(self.executor.results),
            url_before=url_before,
            url_after=url_after,
            screenshot_base64=screenshot,
            page_source_preview=page_source_preview,
        )

        # Update state
        self.current_step_index += 1
        self.state.current_step = self.current_step_index
        self.state.url = url_after
        self.state.extracted_data = dict(self.executor.results)
        self.state.step_history.append(result)
        self.state.screenshot_base64 = screenshot

        if self.executor.workflow_stopped:
            self.state.workflow_stopped = True

        if self.current_step_index >= len(config.workflows):
            self.state.workflow_complete = True

        return result

    def run_to_step(
        self, step_index: int, capture_screenshots: bool = False
    ) -> list[StepResult]:
        """
        Execute workflow up to (but not including) a specific step.

        Args:
            step_index: Step index to run to
            capture_screenshots: Capture screenshot after each step

        Returns:
            List of StepResults for all executed steps
        """
        results = []

        while self.current_step_index < step_index:
            if self.state.workflow_complete or self.state.workflow_stopped:
                break
            result = self.step(capture_screenshot=capture_screenshots)
            results.append(result)

            if not result.success:
                logger.warning(f"Stopping at step {result.step_index} due to error")
                break

        return results

    def run_all(self, capture_screenshots: bool = False) -> list[StepResult]:
        """
        Execute all remaining workflow steps.

        Args:
            capture_screenshots: Capture screenshot after each step

        Returns:
            List of StepResults for all executed steps
        """
        config = self._load_config()
        return self.run_to_step(len(config.workflows), capture_screenshots)

    def skip_to_step(self, step_index: int) -> None:
        """
        Skip to a specific step without executing intermediate steps.

        Note: This may cause issues if skipped steps set up required state.

        Args:
            step_index: Step index to skip to
        """
        self._ensure_executor()

        config = self._load_config()

        if step_index < 0 or step_index >= len(config.workflows):
            raise ValueError(
                f"Invalid step index: {step_index} (max: {len(config.workflows) - 1})"
            )

        self.current_step_index = step_index
        self.state.current_step = step_index
        logger.info(f"Skipped to step {step_index}")

    def inspect_state(self) -> DebugState:
        """
        Inspect current page state without executing any steps.

        Returns:
            DebugState with current page information
        """
        self._ensure_executor()

        # Update state with current page info
        try:
            if hasattr(self.executor, "browser") and hasattr(
                self.executor.browser, "page"
            ):
                page = self.executor.browser.page
                self.state.url = page.url
                self.state.page_title = page.title()
                self.state.page_source = page.content()
                self.state.screenshot_base64 = self._capture_screenshot()
        except Exception as e:
            logger.warning(f"Error inspecting state: {e}")

        self.state.extracted_data = dict(self.executor.results) if self.executor else {}
        self.state.timestamp = datetime.now().isoformat()

        return self.state

    def get_current_step(self) -> dict[str, Any] | None:
        """Get details of the current step to be executed."""
        config = self._load_config()

        if self.current_step_index >= len(config.workflows):
            return None

        step = config.workflows[self.current_step_index]
        return {
            "index": self.current_step_index,
            "action": step.action,
            "params": dict(step.params),
        }

    def get_extracted_data(self) -> dict[str, Any]:
        """Get all data extracted so far."""
        if self.executor:
            return dict(self.executor.results)
        return {}

    def _capture_screenshot(self) -> str | None:
        """Capture current page screenshot as base64."""
        try:
            if hasattr(self.executor, "browser") and hasattr(
                self.executor.browser, "page"
            ):
                screenshot_bytes = self.executor.browser.page.screenshot(type="png")
                return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
        return None

    def _get_page_source(self) -> str | None:
        """Get current page HTML source."""
        try:
            if hasattr(self.executor, "browser") and hasattr(
                self.executor.browser, "page"
            ):
                return self.executor.browser.page.content()
        except Exception as e:
            logger.warning(f"Failed to get page source: {e}")
        return None

    def save_debug_state(self, output_dir: str = ".") -> str:
        """
        Save current debug state to files.

        Args:
            output_dir: Directory to save files to

        Returns:
            Path to the saved state JSON file
        """
        import json

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"debug_state_{timestamp}"

        # Save state JSON
        state_file = output_path / f"{base_name}.json"
        state_data = {
            "current_step": self.state.current_step,
            "total_steps": self.state.total_steps,
            "url": self.state.url,
            "page_title": self.state.page_title,
            "extracted_data": self.state.extracted_data,
            "workflow_complete": self.state.workflow_complete,
            "workflow_stopped": self.state.workflow_stopped,
            "step_history": [
                {
                    "step_index": r.step_index,
                    "action": r.action,
                    "success": r.success,
                    "error": r.error,
                    "timing_ms": r.timing_ms,
                }
                for r in self.state.step_history
            ],
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

        # Save page source if available
        if self.state.page_source:
            source_file = output_path / f"{base_name}.html"
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(self.state.page_source)

        # Save screenshot if available
        if self.state.screenshot_base64:
            screenshot_file = output_path / f"{base_name}.png"
            with open(screenshot_file, "wb") as f:
                f.write(base64.b64decode(self.state.screenshot_base64))

        logger.info(f"Debug state saved to: {state_file}")
        return str(state_file)

    def test_selector(
        self, selector: str, attribute: str | None = None
    ) -> dict[str, Any]:
        """
        Test a selector against the current page.

        Args:
            selector: CSS or XPath selector
            attribute: Attribute to extract (default: text)

        Returns:
            Dict with match count and matched values
        """
        self._ensure_executor()

        try:
            # Normalize XPath selectors
            is_xpath = selector.startswith("//") or selector.startswith(".//")
            query_selector = f"xpath={selector}" if is_xpath else selector

            page = self.executor.browser.page
            elements = page.query_selector_all(query_selector)

            matches = []
            for element in elements[:10]:  # Limit to 10
                try:
                    if attribute == "text" or attribute is None:
                        text = element.inner_text() or element.text_content() or ""
                        matches.append(text.strip()[:200])
                    else:
                        value = element.get_attribute(attribute)
                        matches.append(value)
                except Exception:
                    matches.append(None)

            return {
                "selector": selector,
                "match_count": len(elements),
                "matches": matches,
            }

        except Exception as e:
            return {
                "selector": selector,
                "match_count": 0,
                "error": str(e),
            }


def debug_workflow(
    config_path: str,
    context: dict[str, Any] | None = None,
    headless: bool = False,
) -> StepDebugger:
    """
    Convenience function to create a step debugger for a config.

    Args:
        config_path: Path to YAML config file
        context: Context variables (e.g., {'sku': '123'})
        headless: Run in headless mode

    Returns:
        StepDebugger instance (use as context manager)
    """
    return StepDebugger(
        config_path=config_path,
        context=context,
        headless=headless,
    )
