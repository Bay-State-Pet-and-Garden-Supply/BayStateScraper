from __future__ import annotations

import asyncio
import logging
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("wait")
class WaitAction(BaseAction):
    """Action to wait for a specified amount of time."""

    async def execute(self, params: dict[str, Any]) -> None:
        seconds = params.get("seconds", params.get("timeout", 1))
        logger.debug(f"Waiting for {seconds} seconds")
        await asyncio.sleep(seconds)
