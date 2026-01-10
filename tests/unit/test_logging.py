import logging
import time
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import pytest
from core.api_client import ScraperAPIClient
from utils.api_handler import ScraperAPIHandler


class TestScraperAPIHandler:
    def test_emit_batches_logs(self):
        # Mock API client
        mock_client = MagicMock(spec=ScraperAPIClient)

        # Initialize handler with small buffer size for testing
        handler = ScraperAPIHandler(mock_client, job_id="test-job", buffer_size=3)

        # Create a logger and add handler
        logger = logging.getLogger("test_logger")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        # Log 2 messages (should be buffered)
        logger.info("Message 1")
        logger.info("Message 2")

        mock_client.post_logs.assert_not_called()

        # Log 3rd message (should trigger flush)
        logger.info("Message 3")

        mock_client.post_logs.assert_called_once()
        args = mock_client.post_logs.call_args[0]
        assert args[0] == "test-job"
        assert len(args[1]) == 3
        assert args[1][0]["message"] == "Message 1"
        assert args[1][0]["level"] == "INFO"

    def test_flush_sends_remaining_logs(self):
        mock_client = MagicMock(spec=ScraperAPIClient)
        handler = ScraperAPIHandler(mock_client, job_id="test-job", buffer_size=10)

        logger = logging.getLogger("test_logger_flush")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Message 1")
        mock_client.post_logs.assert_not_called()

        handler.flush()
        mock_client.post_logs.assert_called_once()
