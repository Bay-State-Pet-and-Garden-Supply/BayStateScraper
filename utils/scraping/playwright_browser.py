"""
Playwright browser utility for scrapers.
Parallel to ScraperBrowser but using Playwright's async API.
Includes both Async and Sync implementations to support migration.
"""
from __future__ import annotations


import asyncio
import os
import shutil
import time
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    async_playwright,
)
from playwright.sync_api import (
    Browser as SyncBrowser,
)
from playwright.sync_api import (
    BrowserContext as SyncBrowserContext,
)
from playwright.sync_api import (
    Page as SyncPage,
)
from playwright.sync_api import (
    Playwright as SyncPlaywright,
)
from playwright.sync_api import (
    Response as SyncResponse,
)
from playwright.sync_api import (
    sync_playwright,
)
from playwright_stealth import Stealth

# Removed: from utils.scraping.scraping import get_standard_chrome_options (Selenium-based)


class PlaywrightScraperBrowser:
    """
    Async Playwright-based browser implementation.
    """

    def __init__(
        self,
        site_name: str,
        headless: bool = True,
        profile_suffix: str | None = None,
        custom_options: list[str] | None = None,
        timeout: int = 30,
    ) -> None:
        """
        Initialize browser for scraping.

        Args:
            site_name: Name of the site
            headless: Whether to run in headless mode
            profile_suffix: Optional suffix for profile directory (unused in ephemeral context)
            custom_options: Additional Chrome args to add
            timeout: Default timeout in seconds
        """
        self.site_name = site_name
        self.headless = headless
        self.profile_suffix = profile_suffix
        self.timeout = timeout * 1000  # Convert to ms
        self.custom_options = custom_options or []

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._last_response: Response | None = None
        self._stealth = Stealth()

    async def initialize(self) -> None:
        """Async initialization of Playwright resources."""
        start_time = time.time()
        print(f"[WEB] [{self.site_name}] Initializing Playwright (Async)...")

        try:
            self.playwright = await async_playwright().start()

            # Construct launch arguments
            args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-infobars",
                "--no-first-run",
            ]

            # Add custom options
            if self.custom_options:
                args.extend(self.custom_options)

            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=args,
            )

            # Create context with standard viewport and user agent
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                device_scale_factor=1,
            )

            # Initialize page
            self.page = await self.context.new_page()

            # Apply stealth
            try:
                await self._stealth.apply_stealth_async(self.page)
            except Exception as e:
                # If stealth is not async-compatible or fails
                print(f"[WARN] [{self.site_name}] Failed to apply stealth (Async): {e}")

            # Set timeouts
            self.page.set_default_timeout(self.timeout)
            self.page.set_default_navigation_timeout(self.timeout)

            init_time = time.time() - start_time
            print(f"[WEB] [{self.site_name}] Playwright initialized in {init_time:.2f}s")

        except Exception as e:
            init_time = time.time() - start_time
            print(f"[WEB] [{self.site_name}] Initialization failed after {init_time:.2f}s: {e}")
            await self.quit()
            raise

    async def get(self, url: str) -> None:
        """Navigate to URL."""
        if not self.page:
            raise RuntimeError("Browser not initialized")

        try:
            self._last_response = await self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[WARN] [{self.site_name}] Navigation error: {e}")
            raise

    async def check_http_status(self) -> int | None:
        """Check the HTTP status code of the last response."""
        if self._last_response:
            return self._last_response.status
        return None

    async def quit(self) -> None:
        """Close the browser and cleanup resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            print(f"[LOCK] [{self.site_name}] Playwright browser closed")
        except Exception as e:
            print(f"[WARN] [{self.site_name}] Error closing browser: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    @property
    def current_url(self) -> str:
        """Get current URL (compatibility with Selenium)."""
        if self.page:
            return self.page.url
        return ""

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.quit()

    def __getattr__(self, name: str) -> Any:
        """Delegate methods to the underlying page object."""
        if self.page:
            return getattr(self.page, name)
        raise AttributeError(
            f"'PlaywrightScraperBrowser' object has no attribute '{name}' and page is not initialized"
        )


async def create_playwright_browser(
    site_name: str,
    headless: bool = True,
    profile_suffix: str | None = None,
    custom_options: list[str] | None = None,
    timeout: int = 30,
) -> PlaywrightScraperBrowser:
    """Factory for Async Browser."""
    browser = PlaywrightScraperBrowser(
        site_name,
        headless,
        profile_suffix,
        custom_options,
        timeout,
    )
    await browser.initialize()
    return browser


class SyncPlaywrightScraperBrowser:
    """
    Synchronous Playwright-based browser implementation.
    Drop-in replacement for ScraperBrowser for legacy synchronous workflows.
    """

    def __init__(
        self,
        site_name: str,
        headless: bool = True,
        profile_suffix: str | None = None,
        custom_options: list[str] | None = None,
        timeout: int = 30,
    ) -> None:
        self.site_name = site_name
        self.headless = headless
        self.profile_suffix = profile_suffix
        self.timeout = timeout * 1000
        self.custom_options = custom_options or []

        self.playwright: SyncPlaywright | None = None
        self.browser: SyncBrowser | None = None
        self.context: SyncBrowserContext | None = None
        self.page: SyncPage | None = None
        self._last_response: SyncResponse | None = None
        self._stealth = Stealth()

        self._initialize()

    def _initialize(self) -> None:
        start_time = time.time()
        print(f"[WEB] [{self.site_name}] Initializing Playwright (Sync)...")

        try:
            # We import sync_playwright inside to avoid top-level issues if not installed
            from playwright.sync_api import sync_playwright

            self.playwright = sync_playwright().start()

            args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
                "--disable-infobars",
                "--no-first-run",
            ]
            if self.custom_options:
                args.extend(self.custom_options)

            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=args,
            )

            self.context = self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                device_scale_factor=1,
            )

            self.page = self.context.new_page()
            self._stealth.apply_stealth_sync(self.page)

            self.page.set_default_timeout(self.timeout)
            self.page.set_default_navigation_timeout(self.timeout)

            init_time = time.time() - start_time
            print(f"[WEB] [{self.site_name}] Playwright initialized in {init_time:.2f}s")

        except Exception as e:
            init_time = time.time() - start_time
            print(f"[WEB] [{self.site_name}] Initialization failed after {init_time:.2f}s: {e}")
            self.quit()
            raise

    def get(self, url: str) -> None:
        if not self.page:
            raise RuntimeError("Browser not initialized")
        try:
            self._last_response = self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[WARN] [{self.site_name}] Navigation error: {e}")
            raise

    def check_http_status(self) -> int | None:
        if self._last_response:
            return self._last_response.status
        return None

    def quit(self) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            print(f"[LOCK] [{self.site_name}] Playwright browser closed")
        except Exception as e:
            print(f"[WARN] [{self.site_name}] Error closing browser: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    @property
    def current_url(self) -> str:
        """Get current URL (compatibility with Selenium)."""
        if self.page:
            return self.page.url
        return ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quit()

    def __getattr__(self, name: str) -> Any:
        if self.page:
            return getattr(self.page, name)
        raise AttributeError(f"'SyncPlaywrightScraperBrowser' object has no attribute '{name}'")


def create_sync_playwright_browser(
    site_name: str,
    headless: bool = True,
    profile_suffix: str | None = None,
    custom_options: list[str] | None = None,
    timeout: int = 30,
) -> SyncPlaywrightScraperBrowser:
    """Factory for Sync Browser."""
    return SyncPlaywrightScraperBrowser(
        site_name,
        headless,
        profile_suffix,
        custom_options,
        timeout,
    )
