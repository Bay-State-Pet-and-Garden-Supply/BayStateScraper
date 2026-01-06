import os
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scraper_backend.core.api_client import (
    AuthenticationError,
    ScraperAPIClient,
)


class TestScraperAPIClientAuthentication:
    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            supabase_url="https://test.supabase.co",
            runner_email="runner@test.local",
            runner_password="test-password",
        )
        self.client.supabase_anon_key = "test-anon-key"

    def test_authenticate_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            token = self.client._authenticate()

            assert token == "new-token"
            assert self.client._access_token == "new-token"
            assert self.client._refresh_token == "new-refresh"

    def test_authenticate_invalid_credentials(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Invalid login credentials",
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            with pytest.raises(AuthenticationError) as exc_info:
                self.client._authenticate()

            assert "Invalid login credentials" in str(exc_info.value)

    def test_authenticate_missing_config(self):
        client = ScraperAPIClient()

        with pytest.raises(AuthenticationError) as exc_info:
            client._authenticate()

        assert "Missing authentication configuration" in str(exc_info.value)


class TestScraperAPIClientTokenRefresh:
    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            supabase_url="https://test.supabase.co",
            runner_email="runner@test.local",
            runner_password="test-password",
        )
        self.client.supabase_anon_key = "test-anon-key"
        self.client._access_token = "old-token"
        self.client._refresh_token = "old-refresh"
        self.client._token_expires_at = time.time() + 600

    def test_refresh_token_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "refreshed-token",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            token = self.client._refresh_auth_token()

            assert token == "refreshed-token"
            assert self.client._access_token == "refreshed-token"

    def test_refresh_token_failure_falls_back_to_authenticate(self):
        mock_refresh_response = MagicMock()
        mock_refresh_response.status_code = 401

        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.json.return_value = {
            "access_token": "new-auth-token",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.side_effect = [mock_refresh_response, mock_auth_response]

            token = self.client._refresh_auth_token()

            assert token == "new-auth-token"

    def test_ensure_valid_token_uses_existing_if_not_expired(self):
        self.client._token_expires_at = time.time() + 600

        token = self.client._ensure_valid_token()

        assert token == "old-token"

    def test_ensure_valid_token_refreshes_if_near_expiry(self):
        self.client._token_expires_at = time.time() + 100

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "refreshed-token",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            token = self.client._ensure_valid_token()

            assert token == "refreshed-token"


class TestScraperAPIClientRequests:
    def setup_method(self):
        self.client = ScraperAPIClient(
            api_url="https://app.example.com",
            supabase_url="https://test.supabase.co",
            runner_email="runner@test.local",
            runner_password="test-password",
        )
        self.client.supabase_anon_key = "test-anon-key"
        self.client._access_token = "valid-token"
        self.client._token_expires_at = time.time() + 3600

    def test_make_request_includes_bearer_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch("httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = mock_response

            result = self.client._make_request("GET", "/api/test")

            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            assert "Authorization" in call_kwargs[1]["headers"]
            assert call_kwargs[1]["headers"]["Authorization"] == "Bearer valid-token"

    def test_make_request_retries_on_401(self):
        mock_401_response = MagicMock()
        mock_401_response.status_code = 401

        mock_success_response = MagicMock()
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {"success": True}

        mock_auth_response = MagicMock()
        mock_auth_response.status_code = 200
        mock_auth_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }

        with patch("httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.side_effect = [mock_401_response, mock_success_response]
            mock_instance.post.return_value = mock_auth_response

            result = self.client._make_request("GET", "/api/test")

            assert result == {"success": True}
            assert mock_instance.get.call_count == 2

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
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )

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
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = mock_response

            success = self.client.submit_results(
                job_id="job-123",
                status="completed",
                runner_name="test-runner",
                results={"skus_processed": 10},
            )

            assert success is True
            mock_post.assert_called_once()
