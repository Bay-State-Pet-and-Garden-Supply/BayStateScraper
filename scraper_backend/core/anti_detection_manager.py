"""
Anti-detection manager for web scraping operations.
Provides comprehensive anti-detection capabilities including CAPTCHA detection,
rate limiting, human behavior simulation, and session management.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from typing import TYPE_CHECKING, Any


# Selenium imports removed - migrated to Playwright
# The By class is no longer used - Playwright uses CSS selectors directly via page.locator()
# Keeping this stub class for backwards compatibility with any remaining Selenium-style code
class By:
    """Stub class for Selenium By selectors - Playwright uses page.locator() with CSS selectors."""

    CSS_SELECTOR = "css selector"
    ID = "id"
    NAME = "name"
    XPATH = "xpath"
    CLASS_NAME = "class name"
    TAG_NAME = "tag name"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"


from core.adaptive_retry_strategy import AdaptiveRetryStrategy, FailureContext
from core.captcha_solver import CaptchaSolver, CaptchaSolverConfig
from core.failure_analytics import FailureAnalytics
from core.failure_classifier import FailureClassifier, FailureType
from core.settings_manager import PROJECT_ROOT

if TYPE_CHECKING:
    from utils.scraping.playwright_browser import (
        SyncPlaywrightScraperBrowser as ScraperBrowser,
    )
    from utils.scraping.playwright_browser import (
        create_sync_playwright_browser as create_browser,
    )

logger = logging.getLogger(__name__)

# Constants
SIGNIFICANT_DELAY_THRESHOLD = 0.1
MAX_BACKOFF_DELAY = 300.0  # Maximum 5 minutes for any backoff delay


from pydantic import BaseModel, Field


class AntiDetectionConfig(BaseModel):
    """Configuration for anti-detection modules."""

    enable_captcha_detection: bool = Field(True, description="Enable CAPTCHA detection")
    enable_rate_limiting: bool = Field(True, description="Enable rate limiting")
    enable_human_simulation: bool = Field(True, description="Enable human behavior simulation")
    enable_session_rotation: bool = Field(True, description="Enable session rotation")
    enable_blocking_handling: bool = Field(True, description="Enable blocking page handling")
    captcha_selectors: list[str] = Field(
        default_factory=lambda: [
            "[class*='captcha']",
            "[id*='captcha']",
            "[class*='recaptcha']",
            "[id*='recaptcha']",
            ".g-recaptcha",
            "#captcha-container",
            # Amazon-specific CAPTCHA selectors
            "form[action*='validateCaptcha']",
            "#captchacharacters",
            "img[src*='captcha']",
            ".a-box-inner form[action*='errors/validateCaptcha']",
            "#auth-captcha-image",
            ".cvf-captcha-img",
        ],
        description="CSS selectors for CAPTCHA detection",
    )
    blocking_selectors: list[str] = Field(
        default_factory=lambda: [
            "[class*='blocked']",
            "[id*='blocked']",
            "[class*='banned']",
            "[id*='banned']",
            "[class*='access-denied']",
            "[id*='access-denied']",
            # Amazon-specific blocking selectors
            "form[action*='validateCaptcha']",
            "#auth-error-message-box",
            ".a-alert-error",
            "#robot-check",
        ],
        description="CSS selectors for blocking detection",
    )
    rate_limiting_selectors: list[str] = Field(
        default_factory=lambda: [
            "[class*='rate-limit']",
            "[id*='rate-limit']",
            "[class*='throttle']",
            "[id*='throttle']",
            "[class*='too-many-requests']",
            "[id*='too-many-requests']",
        ],
        description="CSS selectors for rate limiting detection",
    )
    rate_limiting_text_patterns: list[str] = Field(
        default_factory=lambda: [
            r"rate limit",
            r"too many requests",
            r"throttl",
            r"please wait",
            r"temporary.*block",
            r"429",
        ],
        description="Regex patterns for rate limiting detection",
    )
    rate_limit_min_delay: float = Field(1.0, description="Minimum delay for rate limiting")
    rate_limit_max_delay: float = Field(5.0, description="Maximum delay for rate limiting")
    human_simulation_enabled: bool = Field(True, description="Enable human simulation (legacy alias)")
    session_rotation_interval: int = Field(100, description="Requests before session rotation")
    max_retries_on_detection: int = Field(3, description="Max retries on detection")
    captcha_solver_config: CaptchaSolverConfig = Field(
        default_factory=lambda: CaptchaSolverConfig(
            enabled=False,
            service="2captcha",
            api_key="",
            timeout=120,
            polling_interval=5.0,
            max_retries=3,
        ),
        description="CAPTCHA solver configuration",
    )


class AntiDetectionManager:
    """
    Manages anti-detection measures for web scraping operations.

    Provides integrated anti-detection capabilities including:
    - CAPTCHA detection and handling
    - Rate limiting with intelligent delays
    - Human behavior simulation
    - Session rotation
    - Blocking page detection
    """

    def __init__(
        self,
        browser: ScraperBrowser,
        config: AntiDetectionConfig,
        site_name: str = "unknown",
    ):
        """
        Initialize the anti-detection manager.

        Args:
            browser: ScraperBrowser instance
            config: AntiDetectionConfig with module settings
            site_name: Name of the site being scraped (for adaptive learning)
        """
        self.browser = browser
        self.config = config
        self.site_name = site_name
        self.request_count = 0
        self.last_request_time: float = 0.0
        self.session_start_time = time.time()

        # Initialize adaptive retry strategy
        history_path = os.path.join(PROJECT_ROOT, "data", f"adaptive_retry_{site_name}.json")
        self.adaptive_retry_strategy = AdaptiveRetryStrategy(history_file=history_path)

        # Initialize failure analytics
        self.failure_analytics = FailureAnalytics()

        # Initialize modules
        self.captcha_solver = (
            CaptchaSolver(self.config.captcha_solver_config) if config.enable_captcha_detection and self.config.captcha_solver_config.enabled else None
        )
        self.captcha_detector = CaptchaDetector(self.config, self.captcha_solver) if config.enable_captcha_detection else None
        # Get adaptive config for rate limiting
        rate_limit_adaptive_config = None
        if hasattr(self, "adaptive_retry_strategy"):
            rate_limit_adaptive_config = self.adaptive_retry_strategy.get_adaptive_config(FailureType.RATE_LIMITED, self.site_name)

        self.rate_limiter = RateLimiter(self.config, rate_limit_adaptive_config) if config.enable_rate_limiting else None
        self.human_simulator = HumanBehaviorSimulator(self.config) if config.enable_human_simulation else None
        self.session_manager = SessionManager(self.config) if config.enable_session_rotation else None
        self.blocking_handler = BlockingHandler(self.config) if config.enable_blocking_handling else None

        enabled_modules = [
            module
            for module in [
                "captcha",
                "rate_limit",
                "human_sim",
                "session",
                "blocking",
            ]
            if getattr(
                self,
                (
                    f"{module}_detector"
                    if module == "captcha"
                    else (
                        f"{module}_handler"
                        if module == "blocking"
                        else (f"{module}_manager" if module == "session" else (f"{module}_simulator" if module == "human" else f"{module}_limiter"))
                    )
                ),
                None,
            )
            is not None
        ]

        if self.captcha_solver:
            enabled_modules.append("captcha_solver")

        logger.info("AntiDetectionManager initialized with enabled modules: %s", enabled_modules)

    def pre_action_hook(
        self,
        action: str,
        params: dict[str, Any],
        skip_rate_limit_check: bool = False,
    ) -> bool:
        """
        Execute pre-action anti-detection measures.

        Args:
            action: The workflow action being executed
            params: Action parameters
            skip_rate_limit_check: Whether to skip rate limiting detection for this action

        Returns:
            True if action should proceed, False if blocked
        """
        is_ci = os.getenv("CI") == "true"

        try:
            logger.debug(f"Pre-action hook for '{action}' (CI: {is_ci})")

            # Apply rate limiting
            if self.rate_limiter and not skip_rate_limit_check:
                start_time = time.time()
                self.rate_limiter.apply_delay(self.browser.driver)
                delay_duration = time.time() - start_time
                if delay_duration > SIGNIFICANT_DELAY_THRESHOLD:  # Only log significant delays
                    logger.debug(f"Rate limiter applied {delay_duration:.2f}s delay")

            # Simulate human behavior before action
            if self.human_simulator:
                self.human_simulator.simulate_pre_action(action, params)

            # Check for blocking before proceeding
            if self.blocking_handler and self._should_check_blocking(action):
                if self.blocking_handler.detect_blocking(self.browser.driver):
                    logger.warning("Blocking page detected, attempting recovery")
                    return self.blocking_handler.handle_blocking(self.browser.driver)

            # Check for CAPTCHA before proceeding
            if self.captcha_detector and self._should_check_captcha(action):
                if self.captcha_detector.detect_captcha(self.browser.driver):
                    logger.warning("CAPTCHA detected, attempting resolution")
                    return self.captcha_detector.handle_captcha(self.browser.driver)

            # Check session rotation
            if self.session_manager:
                self.session_manager.check_session_rotation(self)

            self.request_count += 1
            logger.debug(f"Pre-action hook completed for '{action}'")
            return True

        except Exception as e:
            logger.error(f"Pre-action hook failed for '{action}': {e}")
            return False

    def post_action_hook(self, action: str, params: dict[str, Any], success: bool) -> None:
        """
        Execute post-action anti-detection measures.

        Args:
            action: The workflow action that was executed
            params: Action parameters
            success: Whether the action succeeded
        """
        try:
            # Simulate human behavior after action
            if self.human_simulator:
                self.human_simulator.simulate_post_action(action, params, success)

            # Update rate limiter with action result
            if self.rate_limiter:
                self.rate_limiter.update_after_action(success)

        except Exception as e:
            logger.error(f"Post-action hook failed: {e}")

    def handle_error(self, error: Exception, action: str, retry_count: int = 0) -> bool:
        """
        Handle errors with adaptive anti-detection recovery strategies.

        Args:
            error: The exception that occurred
            action: The action that failed
            retry_count: Current retry count

        Returns:
            True if error was handled and can retry, False otherwise
        """
        try:
            # Classify the error to determine failure type
            failure_classifier = FailureClassifier()
            failure_context = failure_classifier.classify_exception(error, {"action": action})

            # Get adaptive retry configuration
            adaptive_config = self.adaptive_retry_strategy.get_adaptive_config(failure_context.failure_type, self.site_name, retry_count)

            # Check if we should retry based on adaptive config
            if retry_count >= adaptive_config.max_retries:
                logger.warning(
                    f"Adaptive max retries ({adaptive_config.max_retries}) exceeded for action: {action} (failure: {failure_context.failure_type.value})"
                )
                return False

            # Apply adaptive delay
            delay = self.adaptive_retry_strategy.calculate_delay(adaptive_config, retry_count)
            if delay > 0:
                logger.info(
                    f"Adaptive retry delay for '{action}' - "
                    f"failure: {failure_context.failure_type.value}, "
                    f"retry {retry_count + 1}/{adaptive_config.max_retries}, delay: {delay:.1f}s"
                )
                time.sleep(delay)

            # Check if it's a detection-related error and apply specific handling
            error_str = str(error).lower()

            if "captcha" in error_str and self.captcha_detector:
                logger.info("CAPTCHA-related error detected, attempting recovery")
                success = self.captcha_detector.handle_captcha(self.browser.driver)
                if success:
                    # Record successful recovery for analytics
                    self.failure_analytics.record_failure(
                        site_name=self.site_name,
                        failure_type=failure_context.failure_type,
                        action=action,
                        retry_count=retry_count,
                        context={"error": error_str, "recovery": "captcha_solve"},
                        success_after_retry=True,
                        final_success=True,
                    )

                    # Record successful recovery
                    self.adaptive_retry_strategy.record_failure(
                        FailureContext(
                            site_name=self.site_name,
                            action=action,
                            retry_count=retry_count,
                            context={"error": error_str, "recovery": "captcha_solve"},
                            failure_type=failure_context.failure_type,
                        ),
                        success_after_retry=True,
                        final_success=True,
                    )
                return success

            elif any(term in error_str for term in ["blocked", "banned", "access denied"]) and self.blocking_handler:
                logger.info("Blocking-related error detected, attempting recovery")
                success = self.blocking_handler.handle_blocking(self.browser.driver)
                if success:
                    # Record successful recovery for analytics
                    self.failure_analytics.record_failure(
                        site_name=self.site_name,
                        failure_type=failure_context.failure_type,
                        action=action,
                        retry_count=retry_count,
                        context={"error": error_str, "recovery": "blocking_handled"},
                        success_after_retry=True,
                        final_success=True,
                    )

                    # Record successful recovery
                    self.adaptive_retry_strategy.record_failure(
                        FailureContext(
                            site_name=self.site_name,
                            action=action,
                            retry_count=retry_count,
                            context={"error": error_str, "recovery": "blocking_handled"},
                            failure_type=failure_context.failure_type,
                        ),
                        success_after_retry=True,
                        final_success=True,
                    )
                return success

            elif "timeout" in error_str and self.rate_limiter:
                logger.info("Timeout error detected, applying adaptive rate limiting")
                self.rate_limiter.apply_backoff_delay()
                # Record the timeout handling for analytics
                self.failure_analytics.record_failure(
                    site_name=self.site_name,
                    failure_type=failure_context.failure_type,
                    action=action,
                    retry_count=retry_count,
                    context={"error": error_str, "recovery": "rate_limit_backoff"},
                    success_after_retry=False,
                    final_success=False,
                )

                # Record the timeout handling
                self.adaptive_retry_strategy.record_failure(
                    FailureContext(
                        site_name=self.site_name,
                        action=action,
                        retry_count=retry_count,
                        context={"error": error_str, "recovery": "rate_limit_backoff"},
                        failure_type=failure_context.failure_type,
                    ),
                    success_after_retry=False,  # Will retry
                    final_success=False,
                )
                return True

            # Default session rotation on persistent failures
            if self.session_manager and retry_count >= adaptive_config.session_rotation_threshold:
                logger.info(f"Persistent failures detected ({retry_count} retries), rotating session")
                success = self.session_manager.rotate_session(self)
                if success:
                    # Record successful session rotation for analytics
                    self.failure_analytics.record_failure(
                        site_name=self.site_name,
                        failure_type=failure_context.failure_type,
                        action=action,
                        retry_count=retry_count,
                        context={"error": error_str, "recovery": "session_rotation"},
                        success_after_retry=True,
                        final_success=True,
                    )

                    # Record successful session rotation
                    self.adaptive_retry_strategy.record_failure(
                        FailureContext(
                            site_name=self.site_name,
                            action=action,
                            retry_count=retry_count,
                            context={"error": error_str, "recovery": "session_rotation"},
                            failure_type=failure_context.failure_type,
                        ),
                        success_after_retry=True,
                        final_success=True,
                    )
                return success

            # Record that we're retrying with default strategy for analytics
            self.failure_analytics.record_failure(
                site_name=self.site_name,
                failure_type=failure_context.failure_type,
                action=action,
                retry_count=retry_count,
                context={"error": error_str, "recovery": "default_retry"},
                success_after_retry=False,
                final_success=False,
            )

            # Record that we're retrying with default strategy
            self.adaptive_retry_strategy.record_failure(
                FailureContext(
                    site_name=self.site_name,
                    action=action,
                    retry_count=retry_count,
                    context={"error": error_str, "recovery": "default_retry"},
                    failure_type=failure_context.failure_type,
                ),
                success_after_retry=False,  # Will retry
                final_success=False,
            )

            return True  # Allow retry with adaptive delay already applied

        except Exception as e:
            logger.error(f"Error handling failed: {e}")
            return False

    def _should_check_captcha(self, action: str) -> bool:
        """Determine if CAPTCHA check should be performed for this action."""
        return action in ["navigate", "click", "input_text", "login"]

    def _should_check_blocking(self, action: str) -> bool:
        """Determine if blocking check should be performed for this action."""
        return action in ["navigate", "click"]


class CaptchaDetector:
    """Handles CAPTCHA detection and resolution."""

    def __init__(self, config: AntiDetectionConfig, captcha_solver: CaptchaSolver | None = None):
        self.config = config
        self.captcha_solver = captcha_solver

    def detect_captcha(self, driver) -> bool:
        """Detect if a CAPTCHA is present on the page."""
        try:
            for selector in self.config.captcha_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"CAPTCHA detected using selector: {selector}")
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.error(f"CAPTCHA detection failed: {e}")
            return False

    def handle_captcha(self, driver) -> bool:
        """Attempt to handle CAPTCHA using solver or fallback strategy."""
        max_retries = 2  # Retry up to 2 times

        for attempt in range(max_retries + 1):
            try:
                # Try to solve CAPTCHA using external service if available
                if self.captcha_solver:
                    current_url = driver.current_url
                    logger.info(f"Attempting CAPTCHA resolution using external service (attempt {attempt + 1}/{max_retries + 1})")
                    if self.captcha_solver.solve_captcha(driver, current_url):
                        logger.info("CAPTCHA solved successfully using external service")
                        return True
                    else:
                        logger.warning(f"External CAPTCHA solving failed (attempt {attempt + 1}), trying fallback")

                # Fallback: just wait and retry
                logger.info(f"Attempting CAPTCHA resolution (waiting strategy, attempt {attempt + 1}/{max_retries + 1})")
                wait_time = random.uniform(5, 10) * (attempt + 1)
                # Increase wait time with each attempt
                time.sleep(wait_time)

                # Check if CAPTCHA is still present after waiting
                if not self.detect_captcha(driver):
                    logger.info("CAPTCHA appears to be resolved after waiting")
                    return True

                if attempt < max_retries:
                    logger.info(f"CAPTCHA still present, retrying in {wait_time:.1f}s")
                    time.sleep(wait_time)
                else:
                    logger.warning("CAPTCHA resolution failed after all attempts")
                    return False

            except Exception as e:
                logger.error(f"CAPTCHA handling failed (attempt {attempt + 1}): {e}")
                if attempt == max_retries:
                    return False
                time.sleep(random.uniform(2, 5))  # Brief pause before retry

        return False


class RateLimiter:
    """Manages rate limiting with intelligent delays."""

    def __init__(self, config: AntiDetectionConfig, adaptive_config=None):
        self.config = config
        self.adaptive_config = adaptive_config
        self.last_request_time: float = 0.0
        self.consecutive_failures = 0

    def detect_rate_limiting(self, driver) -> bool:
        """Detect if current page indicates rate limiting."""
        try:
            # Check selectors
            for selector in self.config.rate_limiting_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"Rate limiting detected using selector: {selector}")
                        return True
                except Exception:
                    continue

            # Check page content for text patterns
            page_text = driver.page_source.lower()
            page_title = driver.title.lower()

            for pattern in self.config.rate_limiting_text_patterns:
                if re.search(pattern, page_text, re.IGNORECASE) or re.search(pattern, page_title, re.IGNORECASE):
                    logger.info(f"Rate limiting detected using text pattern: {pattern}")
                    return True

            return False
        except Exception as e:
            logger.error(f"Rate limiting detection failed: {e}")
            return False

    def apply_delay(self, driver=None) -> None:
        """Apply appropriate delay before next request using adaptive strategies."""
        is_ci = os.getenv("CI") == "true"
        # Check for rate limiting indicators on the page before applying delay
        if driver and self.detect_rate_limiting(driver):
            logger.warning("Rate limiting detected on page, applying extended delay")
            # Get adaptive config for rate limiting
            if self.adaptive_config is not None:
                extended_delay = float(self.adaptive_config.max_delay)
            else:
                extended_delay = float(self.config.rate_limit_max_delay * 3)  # 3x normal max delay
            time.sleep(extended_delay)
            self.consecutive_failures += 1  # Treat as failure to increase future delays
            self.last_request_time = time.time()
            return

        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        # Get adaptive configuration if available
        min_delay: float
        max_delay: float
        if self.adaptive_config is not None:
            min_delay = float(self.adaptive_config.base_delay)
            max_delay = float(self.adaptive_config.max_delay)
        # Use reduced delays in CI environment to prevent timeouts
        elif is_ci:
            min_delay = float(min(self.config.rate_limit_min_delay, 0.5))  # Cap at 0.5s
            max_delay = float(min(self.config.rate_limit_max_delay, 2.0))  # Cap at 2.0s
        else:
            min_delay = float(self.config.rate_limit_min_delay)
            max_delay = float(self.config.rate_limit_max_delay)

        # Increase delay based on consecutive failures (with cap to prevent excessive delays)
        if self.consecutive_failures > 0:
            multiplier = min(float(2**self.consecutive_failures), MAX_BACKOFF_DELAY / max_delay)
            max_delay = min(max_delay * multiplier, MAX_BACKOFF_DELAY)

        required_delay = random.uniform(min_delay, max_delay)

        if time_since_last < required_delay:
            applied_delay = required_delay - time_since_last  # type: ignore
            logger.debug(
                f"Rate limiter - CI: {is_ci}, time_since_last: {time_since_last:.2f}s, "
                f"required_delay: {required_delay:.2f}s, applying delay: {applied_delay:.2f}s, "
                f"failures: {self.consecutive_failures}"
            )
            time.sleep(applied_delay)
        else:
            logger.debug(f"Rate limiter - CI: {is_ci}, no delay needed (time_since_last: {time_since_last:.2f}s >= required_delay: {required_delay:.2f}s)")

        self.last_request_time = time.time()

    def apply_backoff_delay(self) -> None:
        """Apply exponential backoff delay with cap to prevent excessive waits."""
        self.consecutive_failures += 1
        # Cap the backoff delay to prevent extremely long waits
        backoff_delay = min(
            float(self.config.rate_limit_max_delay * float(2**self.consecutive_failures)),
            MAX_BACKOFF_DELAY,
        )
        logger.info(f"Applying backoff delay: {backoff_delay:.2f}s (failure #{self.consecutive_failures}, max={MAX_BACKOFF_DELAY}s)")
        time.sleep(backoff_delay)

    def update_after_action(self, success: bool) -> None:
        """Update rate limiting state based on action result."""
        if success:
            self.consecutive_failures = max(0, self.consecutive_failures - 1)
        else:
            self.consecutive_failures += 1


class HumanBehaviorSimulator:
    """Simulates human-like browsing behavior."""

    def __init__(self, config: AntiDetectionConfig):
        self.config = config

    def simulate_pre_action(self, action: str, params: dict[str, Any]) -> None:
        """Simulate human behavior before an action."""
        if action == "click":
            # Random mouse movement before click
            time.sleep(random.uniform(0.1, 0.5))
        elif action == "input_text":
            # Typing delay
            time.sleep(random.uniform(0.05, 0.2))
        elif action == "navigate":
            # Page reading time
            time.sleep(random.uniform(1, 3))

    def simulate_post_action(self, action: str, params: dict[str, Any], success: bool) -> None:
        """Simulate human behavior after an action."""
        if action == "navigate" and success:
            # Simulate reading time
            time.sleep(random.uniform(2, 5))
        elif action == "click" and success:
            # Post-click pause
            time.sleep(random.uniform(0.5, 2))


class SessionManager:
    """Manages browser session rotation."""

    def __init__(self, config: AntiDetectionConfig):
        self.config = config
        self.request_count = 0

    def check_session_rotation(self, manager: AntiDetectionManager) -> None:
        """Check if session should be rotated."""
        self.request_count += 1
        if self.request_count >= self.config.session_rotation_interval:
            logger.info(f"Session rotation triggered after {self.request_count} requests")
            self.rotate_session(manager)

    def rotate_session(self, manager: AntiDetectionManager) -> bool:
        """Rotate the browser session."""
        try:
            from utils.scraping.playwright_browser import (
                create_sync_playwright_browser as create_browser,
            )

            # Close current browser
            if manager.browser:
                manager.browser.quit()

            # Create new browser instance
            manager.browser = create_browser(
                site_name="rotated_session",
                headless=True,  # Assume headless for now
                profile_suffix=f"rotated_{int(time.time())}",
            )

            # Reset counters
            self.request_count = 0
            manager.request_count = 0
            manager.session_start_time = time.time()

            logger.info("Session rotated successfully")
            return True

        except Exception as e:
            logger.error(f"Session rotation failed: {e}")
            return False


class BlockingHandler:
    """Handles blocking page detection and recovery."""

    def __init__(self, config: AntiDetectionConfig):
        self.config = config

    def detect_blocking(self, driver) -> bool:
        """Detect if current page is a blocking page."""
        try:
            for selector in self.config.blocking_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"Blocking page detected using selector: {selector}")
                        return True
                except Exception:
                    continue

            # Check page title/content for blocking indicators
            title = driver.title.lower()
            if any(term in title for term in ["blocked", "banned", "access denied", "forbidden"]):
                logger.info("Blocking page detected in page title")
                return True

            return False

        except Exception as e:
            logger.error(f"Blocking detection failed: {e}")
            return False

    def handle_blocking(self, driver) -> bool:
        """Attempt to handle blocking page."""
        try:
            # For now, just wait and retry - in production, implement proxy rotation, etc.
            logger.info("Attempting blocking page recovery (waiting strategy)")
            time.sleep(random.uniform(30, 60))  # Longer wait for blocking
            return True
        except Exception as e:
            logger.error(f"Blocking handling failed: {e}")
            return False
