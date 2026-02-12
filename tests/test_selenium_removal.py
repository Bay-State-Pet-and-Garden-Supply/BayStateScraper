"""
Tests for Selenium removal from WorkflowExecutor (Task 1).

Note: After Task 7 refactoring, much functionality moved to extracted modules:
- selector_resolver.py (element finding/extraction)
- debug_capture.py (debug artifacts)
- browser_manager.py (browser lifecycle)

These tests verify the main workflow_executor.py has no Selenium references.
Behavioral tests for extracted modules are in their respective test files.
"""

import ast
import os
import re

WORKFLOW_EXECUTOR_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "scrapers",
    "executor",
    "workflow_executor.py",
)


def _read_source() -> str:
    with open(WORKFLOW_EXECUTOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestNoDriverReferences:
    """workflow_executor.py must contain zero '.driver.' references."""

    def test_no_dot_driver_dot_in_source(self):
        source = _read_source()
        matches = re.findall(r"\.driver\.", source)
        assert len(matches) == 0, (
            f"Found {len(matches)} '.driver.' reference(s) in workflow_executor.py. "
            "All Selenium driver references must be replaced with Playwright equivalents."
        )

    def test_no_selenium_import(self):
        source = _read_source()
        tree = ast.parse(source)
        selenium_imports = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module and "selenium" in node.module:
                    selenium_imports.append(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if "selenium" in alias.name:
                            selenium_imports.append(alias.name)
        assert len(selenium_imports) == 0, f"Found selenium import(s): {selenium_imports}. All selenium imports must be removed."

    def test_no_hasattr_driver_checks(self):
        source = _read_source()
        matches = re.findall(r'hasattr\([^)]*["\']driver["\']', source)
        assert len(matches) == 0, f"Found {len(matches)} hasattr(..., 'driver') check(s). All driver capability checks must be removed."


class TestRecoveryUsesPlaywright:
    """Recovery handlers use Playwright APIs, not Selenium."""

    def test_source_contains_page_reload(self):
        """Recovery should use page.reload() not driver.refresh()."""
        source = _read_source()
        assert "page.reload()" in source or "browser.page.reload()" in source, (
            "Recovery handlers must use 'page.reload()' (Playwright), not 'driver.refresh()' (Selenium)."
        )

    def test_source_not_contains_driver_refresh(self):
        """No driver.refresh() references."""
        source = _read_source()
        matches = re.findall(r"\.refresh\(\)", source)
        assert len(matches) == 0, f"Found {len(matches)} '.refresh()' call(s). Use 'page.reload()' instead."

    def test_source_not_contains_driver_delete_all_cookies(self):
        """No driver.delete_all_cookies() references."""
        source = _read_source()
        matches = re.findall(r"delete_all_cookies", source)
        # Allow context.clear_cookies() (Playwright)
        selenium_cookies = [m for m in matches if "driver" in source[source.find(m)-50:source.find(m)]]
        assert len(selenium_cookies) == 0, f"Found Selenium cookie deletion. Use Playwright 'context.clear_cookies()'."
