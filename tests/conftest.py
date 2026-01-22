"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

import pytest


def pytest_configure(config):
    """Configure pytest with required path modifications."""
    project_root = Path(__file__).resolve().parent.parent

    # Add tools directory to path for migration imports
    tools_path = project_root / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))

    # Add scraper_backend to path for schema imports
    scraper_backend_path = project_root / "scraper_backend"
    if str(scraper_backend_path) not in sys.path:
        sys.path.insert(0, str(scraper_backend_path))
