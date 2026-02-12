"""Test: Zero Selenium (.driver.) references in action handlers.

TDD RED test — asserts that all handler files under scrapers/actions/handlers/
contain NO references to Selenium's .driver. attribute, no hasattr checks for
'driver' or 'page' branching, and no Selenium-specific patterns.
"""

from __future__ import annotations

import re
from pathlib import Path


HANDLERS_DIR = Path(__file__).resolve().parent.parent / "scrapers" / "actions" / "handlers"


def _scan_handlers(pattern: str) -> list[tuple[str, int, str]]:
    """Scan all handler .py files for a regex pattern.

    Returns list of (filename, line_number, line_text) matches.
    """
    matches: list[tuple[str, int, str]] = []
    for py_file in sorted(HANDLERS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        for i, line in enumerate(py_file.read_text().splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(pattern, line):
                matches.append((py_file.name, i, line.strip()))
    return matches


def test_no_driver_dot_references() -> None:
    """No handler file should reference .driver. (Selenium WebDriver access)."""
    matches = _scan_handlers(r"\.driver\.")
    assert matches == [], f"Found {len(matches)} .driver. reference(s) in handler files:\n" + "\n".join(f"  {f}:{ln}: {txt}" for f, ln, txt in matches)


def test_no_hasattr_driver_checks() -> None:
    """No handler file should use hasattr(..., 'driver') branching."""
    matches = _scan_handlers(r"hasattr\(.*['\"]driver['\"]\)")
    assert matches == [], f"Found {len(matches)} hasattr(*,'driver') reference(s) in handler files:\n" + "\n".join(
        f"  {f}:{ln}: {txt}" for f, ln, txt in matches
    )


def test_no_hasattr_page_checks() -> None:
    """No handler file should use hasattr(..., 'page') branching.

    Playwright is now the only backend — page is always available.
    """
    matches = _scan_handlers(r"hasattr\(.*['\"]page['\"]\)")
    assert matches == [], f"Found {len(matches)} hasattr(*,'page') reference(s) in handler files:\n" + "\n".join(f"  {f}:{ln}: {txt}" for f, ln, txt in matches)
