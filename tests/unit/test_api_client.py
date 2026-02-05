import os
from unittest.mock import MagicMock, patch

import pytest

from core.api_client import (
    AuthenticationError,
    ScraperAPIClient,
)


class TestScraperAPIClient:
    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            api_key="test-api-key",
            runner_name="test-runner",
        )

    def test_init_sets_attributes(self):
        assert self.client.api_url == "https://app.example.com"
        assert self.client.api_key == "test-api-key"
        assert self.client.runner_name == "test-runner"

    def test_get_headers_includes_api_key(self):
        headers = self.client._get_headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["X-API-Key"] == "test-api-key"

    def test_get_headers_raises_if_no_key(self):
        client = ScraperAPIClient(api_url="https://app.example.com")
        # Ensure env var doesn't interfere
        with patch.dict(os.environ, {}, clear=True):
            client.api_key = None
            with pytest.raises(AuthenticationError):
                client._get_headers()

    def test_make_request_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            mock_instance.get.assert_called_once()
            call_args = mock_instance.get.call_args
            assert call_args[1]["headers"]["X-API-Key"] == "test-api-key"

    def test_make_request_401_raises_auth_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            with pytest.raises(AuthenticationError):
                self.client._make_request("GET", "/api/test")

    def test_get_job_config_parses_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job_id": "job-123",
            "skus": ["SKU001", "SKU002"],
            "scrapers": [{"name": "amazon", "disabled": False}],
            "test_mode": False,
            "max_workers": 3,
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            job_config = self.client.get_job_config("job-123")

            assert job_config is not None
            assert job_config.job_id == "job-123"
            assert len(job_config.skus) == 2
            assert len(job_config.scrapers) == 1
            assert job_config.scrapers[0].name == "amazon"

    def test_submit_results_sends_payload(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value.post
            mock_instance.return_value = mock_response

            success = self.client.submit_results(
                job_id="job-123",
                status="completed",
                results={"skus_processed": 10},
            )

            assert success is True
            mock_instance.assert_called_once()
            # Verify payload contains runner_name from client
            call_args = mock_instance.call_args
            import json

            payload = json.loads(call_args[1]["content"])
            assert payload["runner_name"] == "test-runner"
