import logging
from typing import Any

from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry
from scraper_backend.scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("execute_script")
class ExecuteScriptAction(BaseAction):
    """Action to execute JavaScript."""

    def execute(self, params: dict[str, Any]) -> None:
        script = params.get("script")
        selector = params.get("selector")

        if not script:
            raise WorkflowExecutionError("ExecuteScript action requires 'script' parameter")

        args: list[Any] = []
        if selector:
            # Use Playwright-compatible element finding
            elements = self.executor.find_elements_safe(selector)

            target_element = None
            if elements:
                if params.get("only_visible", False):
                    for el in elements:
                        try:
                            if el.is_visible():
                                target_element = el
                                break
                        except Exception:
                            continue
                    if not target_element:
                        logger.warning(f"No visible element found for selector: {selector}")
                else:
                    target_element = elements[0]

            if target_element:
                args.append(target_element)
            else:
                logger.warning(f"No element found for selector: {selector}, passing no arguments")

        try:
            # Use Playwright's evaluate for script execution
            if hasattr(self.executor.browser, "page"):
                if args:
                    # Evaluate with element argument
                    self.executor.browser.page.evaluate(script, args[0])
                else:
                    self.executor.browser.page.evaluate(script)
            logger.info("Successfully executed JavaScript")

            import time

            wait_time = params.get("wait_after", 0)
            if wait_time > 0:
                time.sleep(wait_time)
        except Exception as e:
            raise WorkflowExecutionError(f"Failed to execute JavaScript: {e}")
