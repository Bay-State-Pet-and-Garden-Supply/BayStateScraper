"""Browser lifecycle management for scraper workflows."""

from __future__ import annotations

import logging
from typing import Any

from utils.scraping.playwright_browser import (
    PlaywrightScraperBrowser as ScraperBrowser,
    create_playwright_browser as create_browser,
)

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages browser lifecycle: init, quit, navigate, HTTP status."""

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30,
        anti_detection_config: dict[str, Any] | None = None,
    ) -> None:
        self.headless = headless
        self.timeout = timeout
        self.anti_detection_config = anti_detection_config
        self.browser: ScraperBrowser | None = None
        self._first_navigation_done = False

    async def initialize(self) -> ScraperBrowser:
        """Initialize and return browser instance."""
        self.browser = await create_browser(site_name="default", headless=self.headless)
        logger.info(f"Browser initialized (headless={self.headless})")
        return self.browser

    async def quit(self) -> None:
        """Quit browser and cleanup."""
        if self.browser:
            await self.browser.quit()
            self.browser = None
            logger.info("Browser quit")

    async def navigate(self, url: str) -> bool:
        """Navigate to URL, return success."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")

        await self.browser.get(url)
        if not self._first_navigation_done:
            self._first_navigation_done = True
        return True

    async def check_http_status(self, url: str | None = None) -> dict[str, Any]:
        """Check HTTP status for URL or current page."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")

        status = await self.browser.check_http_status()
        return {"status": status}

    @property
    def page(self) -> Any:
        """Get current page object."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")
        return self.browser.page

    @property
    def current_url(self) -> str:
        """Get current page URL."""
        if not self.browser:
            raise RuntimeError("Browser not initialized")
        return self.browser.page.url
