from __future__ import annotations

import logging
from typing import Any, cast

from scrapers.actions.base import BaseAction
from scrapers.actions.registry import ActionRegistry
from scrapers.exceptions import WorkflowExecutionError

logger = logging.getLogger(__name__)


@ActionRegistry.register("login")
class LoginAction(BaseAction):
    """Action to execute login workflow with session persistence."""

    def execute(self, params: dict[str, Any]) -> None:
        scraper_name = self.executor.config.name

        # Test mode: Log login selector definitions for testing page
        # Getting test_mode from context (ensure it defaults to False if not present)
        test_mode = getattr(self.executor, "context", {}).get("test_mode", False)

        if test_mode:
            logger.info(f"LoginAction executing in test_mode for {scraper_name}")

        # Check if already authenticated in this session
        if test_mode:
            logger.info(f"Current session auth state: {self.executor.is_session_authenticated()}")

        if self.executor.is_session_authenticated():
            if test_mode:
                logger.info(
                    f"Session already authenticated for {scraper_name}, but verifying selectors in test_mode"
                )
                # If we are already authenticated, we might not be on the login page.
                # In test mode, we should try to go to the login page to verify selectors,
                # UNLESS the success indicator is present (which implies we are logged in).
                # To be safe and show results, we'll try to navigate to login url anyway if test_mode matches.
                # OR we can just emit a status saying "AUTHENTICATED" or similar.
                # Let's emit "FOUND" for success_indicator and "SKIPPED" for others if we are authenticated?
                # Actually, simply navigating to login page again usually redirects to home if logged in,
                # so finding username/password fields might fail.
                #
                # Strategy:
                # 1. Emit success_indicator = FOUND (since we are authenticated)
                # 2. Emit others as SKIPPED or just don't emit them (but UI might show Pending).
                #
                # Better Strategy for "Test Mode":
                # Use a fresh context or force navigation to login page?
                # Using a fresh context is expensive.
                # Let's just assume if we are authenticated, we don't need to re-verify login selectors
                # BUT the user wants to see them.
                #
                # Let's emit a special status "SKIPPED (Auth)" that the frontend can handle?
                # For now, let's just log and skip to match previous behavior but adding a note.
                #
                # Actually, the user PROBABLY wants to verify the selectors still work.
                # So we should probably navigate to login URL even if authenticated in test_mode.
                pass  # Fall through to execute login logic
            else:
                logger.info(
                    f"Skipping login for {scraper_name} - session already authenticated"
                )
                return

        # Merge login details from config into params (safely, if not already done)
        if self.executor.config.login and not params.get("url"):
            params.update(self.executor.config.login.model_dump())

        # Get credentials from settings manager
        if scraper_name == "phillips":
            username, password = self.executor.settings.phillips_credentials
            params["username"] = username  # type: ignore
            params["password"] = password  # type: ignore
        elif scraper_name == "orgill":
            username, password = self.executor.settings.orgill_credentials
            params["username"] = username  # type: ignore
            params["password"] = password  # type: ignore
        elif scraper_name == "petfoodex":
            username, password = self.executor.settings.petfoodex_credentials
            params["username"] = username  # type: ignore
            params["password"] = password  # type: ignore

        username = params.get("username")  # type: ignore
        password = params.get("password")  # type: ignore

        # Ensure credentials are strings
        if username is not None:
            username = str(username)
        if password is not None:
            password = str(password)
        login_url = params.get("url")

        if not username or not password:
            logger.warning(f"Missing credentials for {scraper_name}, skipping login")
            return

        logger.info(f"Logging in to {scraper_name} at {login_url}")

        try:
            # Navigate
            from scrapers.models.config import WorkflowStep

            self.executor._execute_step(WorkflowStep(action="navigate", params={"url": login_url}))

            # In test mode, validate login selectors exist on the page
            if test_mode:
                self._validate_login_selectors(params)

            # Check if already logged in
            success_indicator = params.get("success_indicator")
            if success_indicator:
                try:
                    # Check quickly if we are already logged in
                    self.executor._execute_step(
                        WorkflowStep(
                            action="wait_for",
                            params={"selector": success_indicator, "timeout": 5},
                        )
                    )
                    logger.info(f"Already logged in to {scraper_name}")
                    if test_mode:
                        # If we are already logged in, we can't verify form fields (they are hidden).
                        # Emit 'FOUND' for success indicator, 'SKIPPED' for others.
                        if self.executor.event_emitter:
                            self.executor.event_emitter.login_selector_status(
                                scraper=scraper_name,
                                selector_name="success_indicator",
                                status="FOUND",
                            )
                            for field in ["username_field", "password_field", "submit_button"]:
                                if params.get(field):
                                    self.executor.event_emitter.login_selector_status(
                                        scraper=scraper_name,
                                        selector_name=field,
                                        status="SKIPPED",
                                    )
                    return
                except Exception:
                    # Not logged in (or indicator not found), proceed with login
                    pass

            # Wait for the login form to be ready before inputting credentials
            username_field = params.get("username_field")
            if username_field:
                # Wait for username field to appear (with timeout)
                self.executor._execute_step(
                    WorkflowStep(
                        action="wait_for",
                        params={"selector": username_field, "timeout": 15},
                    )
                )
                # Input username
                self.executor._execute_step(
                    WorkflowStep(
                        action="input_text", params={"selector": username_field, "text": username}
                    )
                )

            # Input password
            password_field = params.get("password_field")
            if password_field:
                self.executor._execute_step(
                    WorkflowStep(
                        action="input_text", params={"selector": password_field, "text": password}
                    )
                )

            # Click submit
            submit_button = params.get("submit_button")
            if submit_button:
                self.executor._execute_step(
                    WorkflowStep(action="click", params={"selector": submit_button})
                )

            # Wait for success
            timeout = params.get("timeout", 30)
            if success_indicator:
                self.executor._execute_step(
                    WorkflowStep(
                        action="wait_for",
                        params={"selector": success_indicator, "timeout": timeout},
                    )
                )
                logger.info("Login successful")

            # In test mode, confirm success indicator was found
            if test_mode and success_indicator:
                logger.info("[LOGIN_SELECTOR] success_indicator: 'FOUND'")

            # Mark session as authenticated
            self.executor.mark_session_authenticated()
        except Exception as e:
            logger.error(f"Login failed for {scraper_name}: {e}")
            raise WorkflowExecutionError(f"Login failed for {scraper_name}: {e}") from e

    def _validate_login_selectors(self, params: dict[str, Any]) -> None:
        """
        Validate presence of login selectors on the page and log results for UI.
        Used in test_mode.
        """
        import time

        # Small wait to ensure page is interactive/loaded beyond basic navigation
        time.sleep(2)

        selectors = {
            "username_field": params.get("username_field"),
            "password_field": params.get("password_field"),
            "submit_button": params.get("submit_button"),
        }

        for name, selector in selectors.items():
            if not selector:
                continue

            # Check if element exists
            element = self.executor.find_element_safe(selector)
            status = "FOUND" if element else "MISSING"

            # Log in format expected by TestingPage: [LOGIN_SELECTOR] name: 'STATUS'
            logger.info(f"[LOGIN_SELECTOR] {name}: '{status}'")

            # Emit event for UI
            if self.executor.event_emitter:
                self.executor.event_emitter.login_selector_status(
                    scraper=self.executor.config.name,
                    selector_name=name,
                    status=status,
                )
