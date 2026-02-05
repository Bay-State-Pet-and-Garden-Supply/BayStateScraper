"""
Tests for structured logging functionality in runner.py.

Tests the structured logging implementation including:
- JSON output format
- Context fields (job_id, scraper_name, trace_id)
- Sensitive data redaction
- Trace ID generation
"""

import json
import logging
import sys
import os

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from scraper_backend.utils.structured_logging import (
    SensitiveDataFilter,
    JSONFormatter,
    generate_trace_id,
    setup_structured_logging,
)
