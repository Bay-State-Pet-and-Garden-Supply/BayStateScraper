from __future__ import annotations
import asyncio

import logging
import time
from typing import Any

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("detect_captcha")
class DetectCaptchaAction(BaseAction):
    """Action to detect CAPTCHA presence on current page."""

    async def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.ctx.anti_detection_manager
            or not self.ctx.anti_detection_manager.captcha_detector
        ):
            logger.warning("CAPTCHA detection not enabled")
            return

        detected = self.ctx.anti_detection_manager.captcha_detector.detect_captcha(
            self.ctx.browser.driver
        )
        self.ctx.results["captcha_detected"] = detected

        if detected:
            logger.info("CAPTCHA detected on current page")
            # Store detection result
            self.ctx.results["captcha_details"] = {
                "detected": True,
                "timestamp": time.time(),
            }
        else:
            logger.debug("No CAPTCHA detected on current page")


@ActionRegistry.register("handle_blocking")
class HandleBlockingAction(BaseAction):
    """Action to handle blocking pages."""

    async def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.ctx.anti_detection_manager
            or not self.ctx.anti_detection_manager.blocking_handler
        ):
            logger.warning("Blocking handling not enabled")
            return

        handled = self.ctx.anti_detection_manager.blocking_handler.handle_blocking(
            self.ctx.browser.driver
        )
        self.ctx.results["blocking_handled"] = handled

        if handled:
            logger.info("Blocking page handled successfully")
        else:
            logger.warning("Failed to handle blocking page")


@ActionRegistry.register("rate_limit")
class RateLimitAction(BaseAction):
    """Action to apply rate limiting delay."""

    async def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.ctx.anti_detection_manager
            or not self.ctx.anti_detection_manager.rate_limiter
        ):
            logger.warning("Rate limiting not enabled")
            return

        delay = params.get("delay", None)
        if delay:
            # Custom delay
            await asyncio.sleep(delay)
            logger.debug(f"Applied custom rate limit delay: {delay}s")
        else:
            # Use rate limiter's intelligent delay
            self.ctx.anti_detection_manager.rate_limiter.apply_delay()
            logger.debug("Applied intelligent rate limiting")


@ActionRegistry.register("simulate_human")
class SimulateHumanAction(BaseAction):
    """Action to simulate human-like behavior."""

    async def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.ctx.anti_detection_manager
            or not self.ctx.anti_detection_manager.human_simulator
        ):
            logger.warning("Human behavior simulation not enabled")
            return

        behavior_type = params.get("behavior", "random")
        duration = params.get("duration", 2.0)

        if behavior_type == "reading":
            await asyncio.sleep(duration)
            logger.debug(f"Simulated reading behavior for {duration}s")
        elif behavior_type == "typing":
            # Simulate typing delay
            await asyncio.sleep(duration * 0.1)  # Shorter for typing
            logger.debug(f"Simulated typing behavior for {duration * 0.1}s")
        elif behavior_type == "navigation":
            await asyncio.sleep(duration)
            logger.debug(f"Simulated navigation pause for {duration}s")
        else:
            # Random human-like pause
            import random

            await asyncio.sleep(random.uniform(1, duration))
            logger.debug(f"Simulated random human behavior for {random.uniform(1, duration):.2f}s")


@ActionRegistry.register("rotate_session")
class RotateSessionAction(BaseAction):
    """Action to force session rotation."""

    async def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.ctx.anti_detection_manager
            or not self.ctx.anti_detection_manager.session_manager
        ):
            logger.warning("Session rotation not enabled")
            return

        rotated = self.ctx.anti_detection_manager.session_manager.rotate_session(
            self.ctx.anti_detection_manager
        )
        self.ctx.results["session_rotated"] = rotated

        if rotated:
            logger.info("Session rotated successfully")
        else:
            logger.warning("Failed to rotate session")
