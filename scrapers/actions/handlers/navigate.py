from __future__ import annotations

import asyncio
import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("navigate")
class NavigateAction(BaseAction):
    """Action to navigate to a URL."""

    async def execute(self, params: dict[str, Any]) -> None:
        url = params.get("url")
        if not url:
            raise WorkflowExecutionError("Navigate action requires 'url' parameter")

        logger.info(f"Navigating to: {url}")
        await self.ctx.browser.get(url)

        # Check HTTP status if monitoring is enabled
        if self.ctx.config.http_status and self.ctx.config.http_status.enabled:
            status_code = self.ctx.browser.check_http_status()
            current_url = self.ctx.browser.current_url

            # Store status in results
            self.ctx.results["http_status"] = status_code
            self.ctx.results["current_url"] = current_url

            # Check for error status codes
            error_codes = params.get("error_codes", [400, 401, 403, 404, 500, 502, 503, 504])
            fail_on_error = params.get("fail_on_error", True)

            if status_code in error_codes:
                error_msg = f"HTTP error status {status_code} detected for {current_url}"
                if fail_on_error:
                    logger.error(error_msg)
                    raise WorkflowExecutionError(error_msg)
                else:
                    logger.warning(error_msg)

        # Optional wait after navigation
        wait_time = params.get("wait_after", 0)
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        # Mark that first navigation is done
        self.ctx.first_navigation_done = True
