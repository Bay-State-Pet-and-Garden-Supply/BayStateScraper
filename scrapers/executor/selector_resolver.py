"""
SelectorResolver - Element finding and value extraction for scraper workflows.

This class handles DOM element location and value extraction from Playwright elements.
Extracted from WorkflowExecutor to follow single responsibility principle.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SelectorResolver:
    """Resolves selectors and extracts values from Playwright elements."""

    def __init__(self, browser: Any) -> None:
        """
        Initialize SelectorResolver.

        Args:
            browser: Browser instance with a `page` attribute (Playwright page)
        """
        self.browser = browser

    async def find_element_safe(self, selector: str, required: bool = True, timeout: int | None = None) -> Any:
        """
        Find a single element using Playwright with retry and error handling.

        Args:
            selector: CSS or XPath selector string
            required: If True, raises error when element not found
            timeout: Optional timeout in milliseconds for waiting

        Returns:
            Playwright ElementHandle or None if not found and not required
        """
        try:
            # Handle XPath explicitly for Playwright if needed
            if selector.startswith("//") or selector.startswith(".//"):
                if not selector.startswith("xpath="):
                    selector = f"xpath={selector}"

            if hasattr(self.browser, "page"):
                if timeout:
                    try:
                        await self.browser.page.wait_for_selector(selector, timeout=timeout)
                    except Exception:
                        if required:
                            raise
                        return None
                return await self.browser.page.query_selector(selector)
            return None
        except Exception as e:
            logger.debug(f"find_element_safe failed for '{selector}': {e}")
            if required:
                raise
            return None

    async def find_elements_safe(self, selector: str, timeout: int | None = None) -> list[Any]:
        """
        Find multiple elements using Playwright.

        Args:
            selector: CSS or XPath selector string
            timeout: Optional timeout in milliseconds for waiting

        Returns:
            List of Playwright ElementHandle objects (may be empty)
        """
        try:
            # Handle XPath explicitly for Playwright
            if selector.startswith("//") or selector.startswith(".//"):
                if not selector.startswith("xpath="):
                    selector = f"xpath={selector}"

            if hasattr(self.browser, "page"):
                if timeout:
                    try:
                        await self.browser.page.wait_for_selector(selector, timeout=timeout)
                    except Exception:
                        pass  # Continue even if wait fails
                return await self.browser.page.query_selector_all(selector)
            return []
        except Exception as e:
            logger.debug(f"find_elements_safe failed for '{selector}': {e}")
            return []

    async def extract_value_from_element(self, element: Any, attribute: str | None = None) -> Any:
        """
        Extract value from element (text, attribute, etc.).

        Args:
            element: Playwright ElementHandle
            attribute: Attribute name to extract, or "text" for text content,
                      or None for default text extraction

        Returns:
            Extracted string value or None if extraction fails
        """
        if element is None:
            return None

        try:
            if attribute == "text" or attribute is None:
                # Try inner_text first, fallback to text_content
                inner_text = await element.inner_text()
                text = inner_text.strip() if inner_text else ""
                if not text:
                    text_content = await element.text_content()
                    text = text_content.strip() if text_content else ""
                return text if text else None

            elif attribute in ["href", "src", "alt", "title", "value"]:
                attr_value = await element.get_attribute(attribute)
                if attr_value is not None:
                    # For href/src, try to resolve full URL
                    if attribute in ["href", "src"] and attr_value.startswith("/"):
                        try:
                            resolved = await element.evaluate(f"el => el.{attribute}")
                            if resolved:
                                return str(resolved)
                        except Exception:
                            pass
                    return str(attr_value)
                return None
            else:
                # Custom attribute
                attr_value = await element.get_attribute(attribute)
                return str(attr_value) if attr_value is not None else None
        except Exception as e:
            logger.warning(f"Failed to extract value from element: {e}")
            return None

    async def extract_multiple_values(self, elements: list[Any], attribute: str | None = None) -> list[Any]:
        """
        Extract values from multiple elements.

        Args:
            elements: List of Playwright ElementHandle objects
            attribute: Attribute name to extract, or None for text

        Returns:
            List of extracted values (may contain None values)
        """
        results = []
        for elem in elements:
            if elem is not None:
                value = await self.extract_value_from_element(elem, attribute)
                results.append(value)
        return results
