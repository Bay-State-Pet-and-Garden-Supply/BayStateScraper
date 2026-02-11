import os
import time
from unittest.mock import MagicMock, patch

import pytest
import httpx

from core.api_client import (
    AuthenticationError,
    ClaimedChunk,
    ConnectionError,
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
        # Create client with empty api_key to test auth error
        with patch.dict(os.environ, {}, clear=True):
            client = ScraperAPIClient(
                api_url="https://app.example.com",
                api_key="",  # Empty key to trigger auth error
            )
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

    def test_claim_chunk_returns_typed_claimed_chunk(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chunk": {
                "chunk_id": "chunk-1",
                "job_id": "job-1",
                "chunk_index": 0,
                "skus": ["SKU001"],
                "scrapers": ["bradley"],
                "test_mode": False,
                "max_workers": 3,
                "lease_token": "lease-1",
                "lease_expires_at": "2026-02-11T10:00:00Z",
            }
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response

            claimed = self.client.claim_chunk("runner-1")

            assert isinstance(claimed, ClaimedChunk)
            assert claimed is not None
            assert claimed.chunk_id == "chunk-1"
            assert claimed.job_id == "job-1"
            assert claimed.skus == ["SKU001"]

    def test_claim_chunk_returns_none_when_no_chunk(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"chunk": None}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response

            claimed = self.client.claim_chunk("runner-1")
            assert claimed is None


class TestRetryLogic:
    """Tests for retry logic with exponential backoff."""

    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            api_key="test-api-key",
            runner_name="test-runner",
            max_retries=2,  # Fewer retries for faster tests
        )

    def test_succeeds_on_first_attempt(self):
        """Request succeeds without any retries."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 1

    def test_retries_on_500_error(self):
        """Request retries on 500 server error and succeeds on second attempt."""
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [
                httpx.HTTPStatusError("500", request=MagicMock(), response=error_response),
                success_response,
            ]

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 2

    def test_retries_on_503_error(self):
        """Request retries on 503 service unavailable and succeeds on third attempt."""
        error_response = MagicMock()
        error_response.status_code = 503
        error_response.text = "Service Unavailable"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [
                httpx.HTTPStatusError("503", request=MagicMock(), response=error_response),
                httpx.HTTPStatusError("503", request=MagicMock(), response=error_response),
                success_response,
            ]

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 3

    def test_no_retry_on_400_error(self):
        """Request fails immediately on 400 client error (not retryable)."""
        error_response = MagicMock()
        error_response.status_code = 400
        error_response.text = "Bad Request"

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = error_response
            # Patch raise_for_status to raise HTTPStatusError
            mock_instance.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError("400", request=MagicMock(), response=error_response)

            with pytest.raises(httpx.HTTPStatusError):
                self.client._make_request("GET", "/api/test")

            assert mock_instance.get.call_count == 1

    def test_no_retry_on_404_error(self):
        """Request fails immediately on 404 not found (not retryable)."""
        error_response = MagicMock()
        error_response.status_code = 404
        error_response.text = "Not Found"

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = error_response
            mock_instance.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError("404", request=MagicMock(), response=error_response)

            with pytest.raises(httpx.HTTPStatusError):
                self.client._make_request("GET", "/api/test")

            assert mock_instance.get.call_count == 1

    def test_no_retry_on_401_error(self):
        """Request fails immediately on 401 unauthorized (not retryable)."""
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.text = "Unauthorized"

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = error_response

            with pytest.raises(AuthenticationError):
                self.client._make_request("GET", "/api/test")

            assert mock_instance.get.call_count == 1

    def test_retries_on_network_error(self):
        """Request retries on network error and succeeds on retry."""
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [
                httpx.NetworkError("Connection refused"),
                success_response,
            ]

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 2

    def test_retries_on_timeout(self):
        """Request retries on timeout and succeeds on retry."""
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [
                httpx.TimeoutException("Request timed out"),
                success_response,
            ]

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 2

    def test_fails_after_max_retries(self):
        """Request fails after exhausting all retry attempts."""
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = httpx.HTTPStatusError("500", request=MagicMock(), response=error_response)

            with pytest.raises(httpx.HTTPStatusError):
                self.client._make_request("GET", "/api/test")

            # Should attempt 3 times (initial + 2 retries with max_retries=2)
            assert mock_instance.get.call_count == 3

    def test_exponential_backoff_timing(self):
        """Verify exponential backoff delays are applied between retries."""
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            with patch("time.sleep") as mock_sleep:
                mock_instance = mock_client.return_value.__enter__.return_value
                mock_instance.get.side_effect = [
                    httpx.NetworkError("Connection refused"),
                    httpx.NetworkError("Connection refused"),
                    success_response,
                ]

                result = self.client._make_request("GET", "/api/test")

                assert result == {"success": True}
                # Check that sleep was called with exponential backoff delays
                # First retry: 1s, Second retry: 2s
                assert mock_sleep.call_count == 2
                mock_sleep.assert_any_call(1.0)  # First retry
                mock_sleep.assert_any_call(2.0)  # Second retry

    def test_retries_on_429_rate_limit(self):
        """Request retries on 429 rate limit and succeeds on retry."""
        error_response = MagicMock()
        error_response.status_code = 429
        error_response.text = "Too Many Requests"

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [
                httpx.HTTPStatusError("429", request=MagicMock(), response=error_response),
                success_response,
            ]

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 2


class TestHealthCheck:
    """Tests for health check functionality."""

    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            api_key="test-api-key",
            runner_name="test-runner",
        )

    def test_health_check_returns_true_on_success(self):
        """Health check returns True when API responds with 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            result = self.client.health_check()

            assert result is True
            mock_instance.get.assert_called_once()
            call_args = mock_instance.get.call_args
            assert "/api/health" in call_args[0][0]
            assert call_args[1]["headers"]["X-API-Key"] == "test-api-key"

    def test_health_check_raises_connection_error_on_missing_url(self):
        """Health check raises ConnectionError when API URL is not configured."""
        client = ScraperAPIClient(
            api_url="",  # Empty URL
            api_key="test-api-key",
        )

        with pytest.raises(ConnectionError) as exc_info:
            client.health_check()

        assert "SCRAPER_API_URL not configured" in str(exc_info.value)

    def test_health_check_raises_connection_error_on_non_200(self):
        """Health check raises ConnectionError when API returns non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            with pytest.raises(ConnectionError) as exc_info:
                self.client.health_check()

            assert "500" in str(exc_info.value)

    def test_health_check_raises_connection_error_on_network_error(self):
        """Health check raises ConnectionError on network failure."""
        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = httpx.NetworkError("Connection refused")

            with pytest.raises(ConnectionError) as exc_info:
                self.client.health_check()

            assert "Network error" in str(exc_info.value)

    def test_health_check_raises_connection_error_on_timeout(self):
        """Health check raises ConnectionError when request times out."""
        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = httpx.TimeoutException("Request timed out")

            with pytest.raises(ConnectionError) as exc_info:
                self.client.health_check()

            assert "timed out" in str(exc_info.value)

    def test_health_check_does_not_use_retry_logic(self):
        """Health check should not retry on failure - single attempt only."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response

            self.client.health_check()

            # Should only make one request (no retries for health check)
            assert mock_instance.get.call_count == 1
