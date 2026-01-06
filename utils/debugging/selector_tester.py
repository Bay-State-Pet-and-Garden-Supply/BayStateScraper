"""
Selector Tester - test individual selectors against live pages.

Provides tools to:
- Test CSS and XPath selectors against live URLs
- Preview matched element content
- Measure timing performance
- Batch test multiple selectors
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SelectorTestResult:
    """Result of testing a single selector."""

    selector: str
    selector_type: str  # "css" or "xpath"
    match_count: int
    matches: list[dict[str, Any]] = field(default_factory=list)
    timing_ms: float = 0.0
    error: str | None = None
    url: str | None = None

    @property
    def success(self) -> bool:
        """Returns True if selector matched at least one element."""
        return self.match_count > 0 and self.error is None

    def __str__(self) -> str:
        if self.error:
            return f"FAIL: {self.selector} - {self.error}"
        return f"{'PASS' if self.success else 'WARN'}: {self.selector} - {self.match_count} matches ({self.timing_ms:.1f}ms)"


@dataclass
class BatchSelectorResult:
    """Result of testing multiple selectors."""

    url: str
    results: list[SelectorTestResult] = field(default_factory=list)
    total_time_ms: float = 0.0
    page_load_time_ms: float = 0.0

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.success)

    def __str__(self) -> str:
        lines = [
            f"Batch Selector Test: {self.url}",
            f"Page load: {self.page_load_time_ms:.1f}ms",
            f"Results: {self.success_count}/{len(self.results)} passed",
            "-" * 40,
        ]
        for result in self.results:
            lines.append(str(result))
        return "\n".join(lines)


class SelectorTester:
    """
    Tests selectors against live web pages.

    Uses Playwright for browser automation to test CSS and XPath
    selectors, returning match counts and element previews.
    """

    def __init__(self, headless: bool = True, timeout: int = 30):
        """
        Initialize the selector tester.

        Args:
            headless: Run browser in headless mode
            timeout: Default timeout in seconds
        """
        self.headless = headless
        self.timeout = timeout
        self.browser: Any = None
        self._initialized = False

    def _ensure_browser(self) -> None:
        """Initialize browser if not already done."""
        if self._initialized and self.browser:
            return

        try:
            from utils.scraping.playwright_browser import (
                create_sync_playwright_browser,
            )

            self.browser = create_sync_playwright_browser(
                site_name="selector_tester",
                headless=self.headless,
                timeout=self.timeout,
            )
            self._initialized = True
            logger.info("Selector tester browser initialized")
        except ImportError:
            # Fallback to direct Playwright if wrapper not available
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser_instance = self._playwright.chromium.launch(
                headless=self.headless
            )
            self._context = self._browser_instance.new_context()
            self.browser = type(
                "BrowserWrapper",
                (),
                {
                    "page": self._context.new_page(),
                    "quit": lambda self: (
                        self._context.close(),
                        self._browser_instance.close(),
                        self._playwright.stop(),
                    ),
                },
            )()
            self._initialized = True
            logger.info("Selector tester initialized with direct Playwright")

    def close(self) -> None:
        """Close the browser."""
        if self.browser:
            try:
                self.browser.quit()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            self.browser = None
            self._initialized = False

    def __enter__(self) -> "SelectorTester":
        self._ensure_browser()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def navigate(self, url: str, wait_for: str | None = None) -> float:
        """
        Navigate to a URL.

        Args:
            url: URL to navigate to
            wait_for: Optional selector to wait for after navigation

        Returns:
            Navigation time in milliseconds
        """
        self._ensure_browser()

        start = time.perf_counter()

        page = self.browser.page
        page.goto(url, timeout=self.timeout * 1000)

        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=self.timeout * 1000)
            except Exception:
                pass  # Don't fail if wait_for selector not found

        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"Navigated to {url} in {elapsed:.1f}ms")
        return elapsed

    def test_selector(
        self,
        selector: str,
        url: str | None = None,
        attribute: str | None = None,
        max_matches: int = 10,
    ) -> SelectorTestResult:
        """
        Test a selector against the current page or a URL.

        Args:
            selector: CSS or XPath selector to test
            url: Optional URL to navigate to first
            attribute: Attribute to extract (default: text content)
            max_matches: Maximum number of match previews to return

        Returns:
            SelectorTestResult with match count and previews
        """
        self._ensure_browser()

        # Determine selector type
        is_xpath = selector.startswith("//") or selector.startswith(".//")
        selector_type = "xpath" if is_xpath else "css"

        # Normalize selector for Playwright
        query_selector = f"xpath={selector}" if is_xpath else selector

        try:
            # Navigate if URL provided
            if url:
                self.navigate(url)

            page = self.browser.page
            current_url = page.url

            # Time the selector query
            start = time.perf_counter()
            elements = page.query_selector_all(query_selector)
            timing_ms = (time.perf_counter() - start) * 1000

            match_count = len(elements)
            matches: list[dict[str, Any]] = []

            # Extract preview data from matches
            for i, element in enumerate(elements[:max_matches]):
                try:
                    match_data: dict[str, Any] = {"index": i}

                    # Get tag name
                    tag = element.evaluate("el => el.tagName.toLowerCase()")
                    match_data["tag"] = tag

                    # Get requested attribute or text
                    if attribute == "text" or attribute is None:
                        text = element.inner_text() or ""
                        match_data["text"] = text[:200].strip() if text else ""
                    elif attribute in ["href", "src", "alt", "title", "value"]:
                        attr_value = element.get_attribute(attribute)
                        match_data[attribute] = attr_value
                    else:
                        attr_value = element.get_attribute(attribute)
                        match_data[attribute] = attr_value

                    # Get outer HTML preview
                    outer_html = element.evaluate("el => el.outerHTML")
                    match_data["html_preview"] = outer_html[:300] if outer_html else ""

                    matches.append(match_data)

                except Exception as e:
                    matches.append({"index": i, "error": str(e)})

            return SelectorTestResult(
                selector=selector,
                selector_type=selector_type,
                match_count=match_count,
                matches=matches,
                timing_ms=timing_ms,
                url=current_url,
            )

        except Exception as e:
            return SelectorTestResult(
                selector=selector,
                selector_type=selector_type,
                match_count=0,
                error=str(e),
                url=url,
            )

    def test_selectors(
        self,
        selectors: list[str] | list[dict[str, Any]],
        url: str,
        wait_for: str | None = None,
    ) -> BatchSelectorResult:
        """
        Test multiple selectors against a URL.

        Args:
            selectors: List of selectors (strings or dicts with 'selector' and optional 'attribute')
            url: URL to test against
            wait_for: Optional selector to wait for after navigation

        Returns:
            BatchSelectorResult with all test results
        """
        self._ensure_browser()

        total_start = time.perf_counter()

        # Navigate first
        page_load_time = self.navigate(url, wait_for)

        results: list[SelectorTestResult] = []

        for sel in selectors:
            if isinstance(sel, str):
                result = self.test_selector(sel)
            else:
                result = self.test_selector(
                    selector=sel.get("selector", ""),
                    attribute=sel.get("attribute"),
                )
            results.append(result)

        total_time = (time.perf_counter() - total_start) * 1000

        return BatchSelectorResult(
            url=url,
            results=results,
            total_time_ms=total_time,
            page_load_time_ms=page_load_time,
        )

    def test_config_selectors(
        self,
        config_path: str,
        url: str | None = None,
        sku: str | None = None,
    ) -> BatchSelectorResult:
        """
        Test all selectors from a scraper config file.

        Args:
            config_path: Path to YAML config file
            url: Optional URL override (uses config base_url + search if not provided)
            sku: Optional SKU to substitute in URL template

        Returns:
            BatchSelectorResult with all selector test results
        """
        import yaml  # type: ignore
        from pathlib import Path

        config_path_obj = Path(config_path)
        with open(config_path_obj, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Get selectors from config
        selectors = config.get("selectors", [])
        if not selectors:
            return BatchSelectorResult(
                url=url or config.get("base_url", ""),
                results=[],
            )

        # Determine URL to test
        test_url = url
        if not test_url:
            base_url = config.get("base_url", "")
            # Try to find navigate action with URL template
            workflows = config.get("workflows", [])
            for step in workflows:
                if step.get("action") == "navigate":
                    nav_url = step.get("params", {}).get("url", "")
                    if nav_url and sku:
                        test_url = nav_url.format(sku=sku)
                        break
            if not test_url:
                test_url = base_url

        # Build selector test list
        selector_tests = []
        for sel in selectors:
            selector_tests.append(
                {
                    "selector": sel.get("selector", ""),
                    "attribute": sel.get("attribute"),
                    "name": sel.get("name"),
                }
            )

        # Test all selectors
        result = self.test_selectors(selector_tests, test_url)

        # Annotate results with selector names
        for i, sel in enumerate(selectors):
            if i < len(result.results):
                result.results[
                    i
                ].selector = (
                    f"{sel.get('name', 'unnamed')}: {result.results[i].selector}"
                )

        return result

    def capture_screenshot(self) -> str:
        """
        Capture current page screenshot as base64.

        Returns:
            Base64 encoded PNG screenshot
        """
        self._ensure_browser()

        page = self.browser.page
        screenshot_bytes = page.screenshot(type="png")
        return base64.b64encode(screenshot_bytes).decode("utf-8")

    def get_page_source(self) -> str:
        """
        Get current page HTML source.

        Returns:
            Page HTML content
        """
        self._ensure_browser()
        return self.browser.page.content()


def test_selector(
    selector: str,
    url: str,
    attribute: str | None = None,
    headless: bool = True,
) -> SelectorTestResult:
    """
    Convenience function to test a single selector.

    Args:
        selector: CSS or XPath selector
        url: URL to test against
        attribute: Attribute to extract
        headless: Run browser in headless mode

    Returns:
        SelectorTestResult
    """
    with SelectorTester(headless=headless) as tester:
        return tester.test_selector(selector, url=url, attribute=attribute)


def test_config_selectors(
    config_path: str,
    sku: str | None = None,
    headless: bool = True,
) -> BatchSelectorResult:
    """
    Convenience function to test all selectors from a config.

    Args:
        config_path: Path to YAML config
        sku: SKU to use for URL template
        headless: Run browser in headless mode

    Returns:
        BatchSelectorResult
    """
    with SelectorTester(headless=headless) as tester:
        return tester.test_config_selectors(config_path, sku=sku)
