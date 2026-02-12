from __future__ import annotations
import asyncio

import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("configure_browser")
class ConfigureBrowserAction(BaseAction):
    """Action to configure browser settings dynamically."""

    async def execute(self, params: dict[str, Any]) -> None:
        block_resources = params.get("block_resources", [])

        if not block_resources:
            return

        try:
            for pattern in block_resources:
                self.ctx.browser.page.route(pattern, lambda route: route.abort())
            logger.info(f"Blocked resources: {block_resources}")
        except Exception as e:
            logger.warning(f"Failed to block resources: {e}")
