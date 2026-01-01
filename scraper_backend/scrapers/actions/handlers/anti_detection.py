import logging
import time
from typing import Any

from scraper_backend.scrapers.actions.base import BaseAction
from scraper_backend.scrapers.actions.registry import ActionRegistry

logger = logging.getLogger(__name__)


@ActionRegistry.register("detect_captcha")
class DetectCaptchaAction(BaseAction):
    """Action to detect CAPTCHA presence on current page."""

    def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.executor.anti_detection_manager
            or not self.executor.anti_detection_manager.captcha_detector
        ):
            logger.warning("CAPTCHA detection not enabled")
            return

        detected = self.executor.anti_detection_manager.captcha_detector.detect_captcha(
            self.executor.browser.driver
        )
        self.executor.results["captcha_detected"] = detected

        if detected:
            logger.info("CAPTCHA detected on current page")
            # Store detection result
            self.executor.results["captcha_details"] = {
                "detected": True,
                "timestamp": time.time(),
            }
        else:
            logger.debug("No CAPTCHA detected on current page")


@ActionRegistry.register("handle_blocking")
class HandleBlockingAction(BaseAction):
    """Action to handle blocking pages."""

    def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.executor.anti_detection_manager
            or not self.executor.anti_detection_manager.blocking_handler
        ):
            logger.warning("Blocking handling not enabled")
            return

        handled = self.executor.anti_detection_manager.blocking_handler.handle_blocking(
            self.executor.browser.driver
        )
        self.executor.results["blocking_handled"] = handled

        if handled:
            logger.info("Blocking page handled successfully")
        else:
            logger.warning("Failed to handle blocking page")


@ActionRegistry.register("rate_limit")
class RateLimitAction(BaseAction):
    """Action to apply rate limiting delay."""

    def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.executor.anti_detection_manager
            or not self.executor.anti_detection_manager.rate_limiter
        ):
            logger.warning("Rate limiting not enabled")
            return

        delay = params.get("delay", None)
        if delay:
            # Custom delay
            time.sleep(delay)
            logger.debug(f"Applied custom rate limit delay: {delay}s")
        else:
            # Use rate limiter's intelligent delay
            self.executor.anti_detection_manager.rate_limiter.apply_delay()
            logger.debug("Applied intelligent rate limiting")


@ActionRegistry.register("simulate_human")
class SimulateHumanAction(BaseAction):
    """Action to simulate human-like behavior."""

    def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.executor.anti_detection_manager
            or not self.executor.anti_detection_manager.human_simulator
        ):
            logger.warning("Human behavior simulation not enabled")
            return

        behavior_type = params.get("behavior", "random")
        duration = params.get("duration", 2.0)

        if behavior_type == "reading":
            time.sleep(duration)
            logger.debug(f"Simulated reading behavior for {duration}s")
        elif behavior_type == "typing":
            # Simulate typing delay
            time.sleep(duration * 0.1)  # Shorter for typing
            logger.debug(f"Simulated typing behavior for {duration * 0.1}s")
        elif behavior_type == "navigation":
            time.sleep(duration)
            logger.debug(f"Simulated navigation pause for {duration}s")
        else:
            # Random human-like pause
            import random

            time.sleep(random.uniform(1, duration))
            logger.debug(f"Simulated random human behavior for {random.uniform(1, duration):.2f}s")


@ActionRegistry.register("rotate_session")
class RotateSessionAction(BaseAction):
    """Action to force session rotation."""

    def execute(self, params: dict[str, Any]) -> None:
        if (
            not self.executor.anti_detection_manager
            or not self.executor.anti_detection_manager.session_manager
        ):
            logger.warning("Session rotation not enabled")
            return

        rotated = self.executor.anti_detection_manager.session_manager.rotate_session(
            self.executor.anti_detection_manager
        )
        self.executor.results["session_rotated"] = rotated

        if rotated:
            logger.info("Session rotated successfully")
        else:
            logger.warning("Failed to rotate session")
