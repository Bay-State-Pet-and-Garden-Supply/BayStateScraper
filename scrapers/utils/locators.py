"""
Locator Utilities - Shared Playwright locator conversion logic.
Broken out to prevent circular imports between actions and executor.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def convert_to_playwright_locator(page: Any, selector: str) -> Any:
    """
    Convert selector strings to proper Playwright locators using best practices.

    Supports:
    - Standard CSS selectors (passed through)
    - XPath selectors (prefixed with xpath=)
    - text='...' → get_by_text()
    - h3:has-text('text') → locator('h3').filter(has_text='text')
    - span:has-text('text') → locator('span').filter(has_text='text')

    Returns a Playwright locator object.
    """
    selector = selector.strip()

    # Handle text= selector (legacy but still used)
    # e.g., "text='View product'" → get_by_text('View product')
    text_match = re.match(r"^text=['\"](.+?)['\"]\s*$", selector)
    if text_match:
        text_content = text_match.group(1)
        logger.debug(f"Converting text= selector to get_by_text: {text_content}")
        return page.get_by_text(text_content, exact=False)

    # Handle :has-text() pseudo-class (Playwright-specific)
    # e.g., "h3:has-text('Sorry, no results')" → locator('h3').filter(has_text='Sorry, no results')
    has_text_match = re.match(r"^(.+?):has-text\(['\"](.+?)['\"]\s*\)$", selector)
    if has_text_match:
        base_selector = has_text_match.group(1).strip()
        text_content = has_text_match.group(2)
        logger.debug(f"Converting :has-text() to locator().filter(): base={base_selector}, text={text_content}")
        return page.locator(base_selector).filter(has_text=text_content)

    # Handle XPath selectors
    if selector.startswith("//") or selector.startswith(".//"):
        if not selector.startswith("xpath="):
            selector = f"xpath={selector}"

    # Standard CSS or XPath - use locator
    return page.locator(selector)
