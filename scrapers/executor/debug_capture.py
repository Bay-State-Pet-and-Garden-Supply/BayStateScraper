"""
Debug artifact capture for scraper workflows.

Extracted from WorkflowExecutor to enable reusable debug state capture.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class BrowserPage(Protocol):
    """Protocol for browser page interface."""

    @property
    def url(self) -> str: ...

    async def content(self) -> str: ...

    async def screenshot(self, *, type: str = "png") -> bytes: ...


class DebugArtifactCapture:
    """
    Captures debug artifacts (screenshots, page source) for scraper workflows.

    Extracted from WorkflowExecutor to enable reusable debug state capture
    without coupling to the executor lifecycle.
    """

    def __init__(
        self,
        job_id: str | None = None,
        scraper_name: str | None = None,
        debug_mode: bool = False,
        output_dir: str | Path | None = None,
        debug_callback: Any | None = None,
    ) -> None:
        """
        Initialize the debug artifact capture.

        Args:
            job_id: Unique job identifier for naming artifacts
            scraper_name: Name of the scraper for context
            debug_mode: Whether debug capture is enabled
            output_dir: Directory to save artifacts (default: current working directory)
            debug_callback: Optional callback for debug data (e.g., debug_context)
        """
        self.job_id = job_id
        self.scraper_name = scraper_name
        self.debug_mode = debug_mode
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.debug_callback = debug_callback

    async def capture_debug_state(
        self,
        step_name: str,
        page: BrowserPage | None = None,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        """
        Capture current state for debugging.

        Captures page source, screenshot, URL, and metadata. If debug_mode is
        enabled and a callback is configured, sends data to the callback.
        Always attempts to dump page source to a local file.

        Args:
            step_name: Name of the current workflow step
            page: Browser page instance (optional, must have url/content/screenshot methods)
            context: Additional context data (e.g., {'sku': 'ABC123'})
            error: Exception that caused the failure (if any)

        Returns:
            Dictionary with captured debug data
        """
        debug_data: dict[str, Any] = {
            "step": step_name,
            "scraper": self.scraper_name,
            "timestamp": datetime.now().isoformat(),
        }

        if self.job_id:
            debug_data["job_id"] = self.job_id

        if context:
            debug_data.update(context)

        if error:
            debug_data["error"] = str(error)
            debug_data["error_type"] = type(error).__name__

        # Always dump to local file for backwards compatibility
        if page and hasattr(page, "content"):
            try:
                page_source = await page.content()
                self._dump_to_file("debug_dump.html", page_source)
                debug_data["page_source_path"] = str(self.output_dir / "debug_dump.html")
            except Exception as dump_e:
                logger.debug(f"Failed to dump page source to file: {dump_e}")

        # If debug mode is not enabled, skip callback capture
        if not self.debug_mode:
            return debug_data

        # Capture detailed debug state
        if page:
            # Get current URL
            try:
                if hasattr(page, "url"):
                    debug_data["url"] = page.url
            except Exception:
                pass

            # Capture page source
            try:
                if hasattr(page, "content"):
                    page_source = await page.content()
                    debug_data["page_source"] = page_source
            except Exception as e:
                logger.debug(f"Failed to capture page source: {e}")

            # Capture screenshot
            try:
                if hasattr(page, "screenshot"):
                    screenshot_bytes = await page.screenshot(type="png")
                    debug_data["screenshot_bytes"] = screenshot_bytes
                    debug_data["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception as e:
                logger.debug(f"Failed to capture screenshot: {e}")

        # Send to callback if configured
        if self.debug_callback:
            try:
                callback_data = {
                    "sku": context.get("sku") if context else None,
                    "scraper": self.scraper_name,
                    "step": step_name,
                    "url": debug_data.get("url"),
                    "error": str(error) if error else "Step failed",
                }

                if "page_source" in debug_data:
                    callback_data["page_source"] = debug_data["page_source"]

                if "screenshot_base64" in debug_data:
                    callback_data["screenshot"] = debug_data["screenshot_base64"]

                self.debug_callback(callback_data)
            except Exception as ex:
                logger.debug(f"Debug callback failed: {ex}")

        logger.debug(f"Captured debug artifacts for job {self.job_id}, step {step_name}")

        return debug_data

    async def save_screenshot(
        self,
        page: BrowserPage | None = None,
        filename: str | None = None,
    ) -> str | None:
        """
        Save screenshot, return path.

        Args:
            page: Browser page instance (must have screenshot method)
            filename: Optional filename (default: debug_screenshot_{job_id}_{timestamp}.png)

        Returns:
            Path to saved screenshot or None if failed
        """
        if not page or not hasattr(page, "screenshot"):
            logger.debug("No page available for screenshot capture")
            return None

        try:
            screenshot_bytes = await page.screenshot(type="png")

            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                job_part = f"_{self.job_id}" if self.job_id else ""
                filename = f"debug_screenshot{job_part}_{timestamp}.png"

            filepath = self.output_dir / filename
            filepath.write_bytes(screenshot_bytes)

            logger.debug(f"Saved screenshot to {filepath}")
            return str(filepath)

        except Exception as e:
            logger.debug(f"Failed to save screenshot: {e}")
            return None

    async def save_page_source(
        self,
        page: BrowserPage | None = None,
        filename: str | None = None,
    ) -> str | None:
        """
        Save page source, return path.

        Args:
            page: Browser page instance (must have content method)
            filename: Optional filename (default: debug_source_{job_id}_{timestamp}.html)

        Returns:
            Path to saved page source or None if failed
        """
        if not page or not hasattr(page, "content"):
            logger.debug("No page available for page source capture")
            return None

        try:
            page_source = await page.content()

            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                job_part = f"_{self.job_id}" if self.job_id else ""
                filename = f"debug_source{job_part}_{timestamp}.html"

            filepath = self.output_dir / filename
            filepath.write_text(page_source, encoding="utf-8")

            logger.debug(f"Saved page source to {filepath}")
            return str(filepath)

        except Exception as e:
            logger.debug(f"Failed to save page source: {e}")
            return None

    def _dump_to_file(self, filename: str, content: str) -> str | None:
        """
        Dump content to a file in the output directory.

        Args:
            filename: Name of the file to write
            content: Content to write to the file

        Returns:
            Path to the written file or None if failed
        """
        try:
            filepath = self.output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            logger.debug(f"Dumped content to {filepath}")
            return str(filepath)
        except Exception as e:
            logger.debug(f"Failed to dump content to file: {e}")
            return None
