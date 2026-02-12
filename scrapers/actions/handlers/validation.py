from __future__ import annotations
import asyncio

import logging
from typing import Any

from core.failure_classifier import FailureType
from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("validate_http_status")
class ValidateHttpStatusAction(BaseAction):
    """Action to validate HTTP status of current page."""

    async def execute(self, params: dict[str, Any]) -> None:
        expected_status = params.get("expected_status")
        fail_on_error = params.get("fail_on_error", True)
        error_codes = params.get("error_codes", [400, 401, 403, 404, 500, 502, 503, 504])

        status_code = self.ctx.browser.check_http_status()
        current_url = self.ctx.browser.page.url

        if status_code is None:
            if fail_on_error:
                logger.error(f"Could not determine HTTP status for {current_url}")
                raise WorkflowExecutionError(f"Failed to determine HTTP status for {current_url}")
            else:
                logger.warning(f"Could not determine HTTP status for {current_url}")
                return

        logger.debug(f"Validated HTTP status for {current_url}: {status_code}")

        # Store status in results
        self.ctx.results["validated_http_status"] = status_code
        self.ctx.results["validated_http_url"] = current_url

        # Check expected status if specified
        if expected_status is not None:
            if status_code != expected_status:
                error_msg = f"HTTP status mismatch: expected {expected_status}, got {status_code} for {current_url}"
                if fail_on_error:
                    logger.error(error_msg)
                    raise WorkflowExecutionError(error_msg)
                else:
                    logger.warning(error_msg)

        # Check for error status codes
        if status_code in error_codes:
            error_msg = f"HTTP error status {status_code} detected for {current_url}"
            if fail_on_error:
                logger.error(error_msg)
                raise WorkflowExecutionError(error_msg)
            else:
                logger.warning(error_msg)


@ActionRegistry.register("check_no_results")
class CheckNoResultsAction(BaseAction):
    """
    Action to explicitly check if the current page indicates a 'no results' scenario.
    Sets 'no_results_found' in results to True if detected.
    Uses fast selector and text pattern matching only (no slow classifier).
    """

    async def execute(self, params: dict[str, Any]) -> None:
        # Get config validation patterns if available
        if self.ctx.config.validation:
            config_no_results = self.ctx.config.validation.no_results_selectors or []
            config_text_patterns = self.ctx.config.validation.no_results_text_patterns or []
        else:
            config_no_results = []
            config_text_patterns = []

        await self._execute_playwright(config_no_results, config_text_patterns)

    def _emit_no_results_event(self) -> None:
        """Helper to emit sku.no_results event if possible."""
        if hasattr(self.ctx, "event_emitter") and self.ctx.event_emitter:
            sku = self.ctx.context.get("sku") if hasattr(self.ctx, "context") else None
            # If SKU not in context, try results
            if not sku:
                sku = self.ctx.results.get("sku")

            if sku:
                self.ctx.event_emitter.sku_no_results(scraper=self.ctx.config.name, worker_id=self.ctx.worker_id or "unknown", sku=sku)

    async def _execute_playwright(self, config_no_results: list[str], config_text_patterns: list[str]) -> None:
        """Execute no-results check using Playwright."""
        import time

        page = self.ctx.browser.page

        try:
            # Fast selector check - only use config selectors (limit to first 5 for speed)
            for selector in config_no_results[:5]:
                try:
                    # Handle XPath vs CSS selectors
                    if selector.startswith("//") or selector.startswith("(//"):
                        locator = page.locator(f"xpath={selector}")
                    else:
                        locator = page.locator(selector)

                    # Quick check with short timeout
                    count = locator.count()
                    logger.info(f"DEBUG: Checking selector '{selector}' - found {count} elements")

                    if count > 0:
                        # Check if visible
                        try:
                            if locator.first.is_visible():
                                # Potential match found - wait and verify it persists
                                logger.info(f"Potential no-results detected via {selector}, verifying persistence...")
                                await asyncio.sleep(2)

                                # Re-check
                                if locator.count() > 0 and locator.first.is_visible():
                                    logger.info(f"No results CONFIRMED via selector: {selector}")
                                    self.ctx.results["no_results_found"] = True
                                    self._emit_no_results_event()
                                    return
                                else:
                                    logger.info(f"No results indicator {selector} disappeared - likely false positive.")
                                    continue
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking selector {selector}: {e}")
                    continue

            # Fast text pattern check in page content (visible text only)
            if config_text_patterns:
                try:
                    # Use inner_text('body') to get only visible text, not hidden templates
                    page_content = page.inner_text("body").lower()
                    logger.info(f"DEBUG: Checking text patterns in visible page text (length: {len(page_content)})")

                    for pattern in config_text_patterns:
                        if pattern.lower() in page_content:
                            logger.info(f"No results detected via text pattern: {pattern}")
                            self.ctx.results["no_results_found"] = True
                            self._emit_no_results_event()
                            return
                        else:
                            logger.info(f"DEBUG: Pattern '{pattern}' NOT found in page content")
                except Exception as e:
                    logger.debug(f"Error checking text patterns: {e}")

            self.ctx.results["no_results_found"] = False

        except Exception as e:
            logger.debug(f"Error during Playwright no-results check: {e}")
            self.ctx.results["no_results_found"] = False


@ActionRegistry.register("conditional_skip")
class ConditionalSkipAction(BaseAction):
    """
    Action to conditionally skip the rest of the workflow based on a flag in results.
    """

    async def execute(self, params: dict[str, Any]) -> None:
        if_flag = params.get("if_flag")
        if not if_flag:
            raise WorkflowExecutionError("conditional_skip action requires 'if_flag' parameter")

        if self.ctx.results.get(if_flag):
            logger.info(f"Condition '{if_flag}' is true, stopping workflow execution.")
            self.ctx.workflow_stopped = True


@ActionRegistry.register("scroll")
class ScrollAction(BaseAction):
    """Action to scroll the page."""

    async def execute(self, params: dict[str, Any]) -> None:
        direction = params.get("direction", "down")
        amount = params.get("amount")
        selector = params.get("selector")

        page = self.ctx.browser.page
        if selector:
            try:
                if selector.startswith("//") or selector.startswith("(//"):
                    locator = page.locator(f"xpath={selector}")
                else:
                    locator = page.locator(selector)
                locator.first.scroll_into_view_if_needed()
                logger.debug(f"Scrolled to element: {selector}")
            except Exception:
                raise WorkflowExecutionError(f"Scroll target element not found: {selector}")
        elif direction == "to_bottom":
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            logger.debug("Scrolled to bottom of page")
        elif direction == "to_top":
            page.evaluate("window.scrollTo(0, 0);")
            logger.debug("Scrolled to top of page")
        else:
            scroll_amount = amount if amount is not None else "window.innerHeight"
            if direction == "down":
                page.evaluate(f"window.scrollBy(0, {scroll_amount});")
                logger.debug(f"Scrolled down by {scroll_amount} pixels")
            elif direction == "up":
                page.evaluate(f"window.scrollBy(0, -{scroll_amount});")
                logger.debug(f"Scrolled up by {scroll_amount} pixels")


@ActionRegistry.register("conditional_click")
class ConditionalClickAction(BaseAction):
    """Action to click on an element only if it exists, without failing the workflow."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        if not selector:
            raise WorkflowExecutionError("conditional_click requires 'selector' parameter")

        timeout = params.get("timeout", 2)

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

            page = self.ctx.browser.page
            selectors_to_try = [s.strip() for s in selector.split(",")]
            element_found = False

            for sel in selectors_to_try:
                try:
                    if sel.startswith("//") or sel.startswith("(//"):
                        locator = page.locator(f"xpath={sel}")
                    else:
                        locator = page.locator(sel)

                    locator.first.wait_for(state="attached", timeout=timeout * 1000)
                    element_found = True
                    logger.info(f"Conditional element '{sel}' found. Attempting to click.")
                    locator.first.click(timeout=5000)
                    logger.info(f"Conditional click succeeded on '{sel}'")
                    break
                except PlaywrightTimeoutError:
                    continue
                except Exception as click_err:
                    logger.debug(f"Conditional click on '{sel}' failed: {click_err}")
                    continue

            if not element_found:
                logger.info(f"Conditional element '{selector}' not found. Skipping click.")

        except Exception as e:
            logger.warning(f"Conditional click on '{selector}' failed with an unexpected error: {e}")


@ActionRegistry.register("verify")
class VerifyAction(BaseAction):
    """Action to verify a value on the page against an expected value."""

    async def execute(self, params: dict[str, Any]) -> None:
        selector = params.get("selector")
        attribute = params.get("attribute", "text")
        expected_value = params.get("expected_value")
        match_mode = params.get("match_mode", "exact")
        on_failure = params.get("on_failure", "fail_workflow")

        if not all([selector, expected_value]):
            raise WorkflowExecutionError("Verify action requires 'selector' and 'expected_value' parameters")

        # Type narrowing after validation
        assert selector is not None

        try:
            elements = self.ctx.find_elements_safe(selector)
            if not elements:
                raise ValueError(f"No element found for selector: {selector}")
            element = elements[0]
            actual_value = self.ctx._extract_value_from_element(element, attribute)

            if actual_value is None:
                raise ValueError("Could not extract actual value from element")

            match = False
            if match_mode == "exact":
                match = str(actual_value) == str(expected_value)
            elif match_mode == "contains":
                match = str(expected_value) in str(actual_value)
            elif match_mode == "fuzzy_number":
                import re

                expected_digits = re.sub(r"\D", "", str(expected_value))
                actual_digits = re.sub(r"\D", "", str(actual_value))
                if expected_digits and actual_digits:
                    match = int(expected_digits) == int(actual_digits)
            else:
                raise WorkflowExecutionError(f"Unknown match_mode: {match_mode}")

            if match:
                logger.info(f"Verification successful for selector '{selector}'. Found '{actual_value}', expected '{expected_value}' (mode: {match_mode}).")
            else:
                error_msg = f"Verification failed for selector '{selector}'. Found '{actual_value}', expected '{expected_value}' (mode: {match_mode})."
                if on_failure == "fail_workflow":
                    raise WorkflowExecutionError(error_msg)
                else:
                    logger.warning(error_msg)

        except Exception as e:
            # Handle both Selenium NoSuchElementException and other errors
            error_msg = f"Verification failed: could not find or extract value from selector '{selector}'. Reason: {e}"
            if on_failure == "fail_workflow":
                raise WorkflowExecutionError(error_msg)
            else:
                logger.warning(error_msg)
