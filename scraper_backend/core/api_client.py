"""
HTTP API client for communicating with BayStateApp coordinator.

Uses JWT authentication via Supabase Auth password grant flow.
Runners have NO database credentials - all communication is via authenticated HTTP endpoints.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TOKEN_REFRESH_BUFFER_SECONDS = 300


@dataclass
class ScraperConfig:
    """Configuration for a single scraper."""

    name: str
    disabled: bool = False
    base_url: str | None = None
    search_url_template: str | None = None
    selectors: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    test_skus: list[str] | None = None


@dataclass
class JobConfig:
    """Job configuration received from the coordinator."""

    job_id: str
    skus: list[str]
    scrapers: list[ScraperConfig]
    test_mode: bool = False
    max_workers: int = 3


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


class ScraperAPIClient:
    """
    HTTP client for communicating with the BayStateApp coordinator API.

    Handles:
    - JWT authentication via Supabase password grant
    - Automatic token refresh before expiry
    - Fetching job configurations and scraper configs
    - Submitting scrape results
    - Status updates and heartbeats
    """

    def __init__(
        self,
        api_url: str | None = None,
        supabase_url: str | None = None,
        runner_email: str | None = None,
        runner_password: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_url = api_url or os.environ.get("SCRAPER_API_URL", "")
        self.supabase_url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self.runner_email = runner_email or os.environ.get("RUNNER_EMAIL", "")
        self.runner_password = runner_password or os.environ.get("RUNNER_PASSWORD", "")
        self.supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        self.runner_name = os.environ.get("RUNNER_NAME", "unknown-runner")
        self.timeout = timeout

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0

        if not self.api_url:
            logger.warning("SCRAPER_API_URL not configured")
        if not self.supabase_url:
            logger.warning("SUPABASE_URL not configured")
        if not self.runner_email or not self.runner_password:
            logger.warning("RUNNER_EMAIL or RUNNER_PASSWORD not configured")

    def _authenticate(self) -> str:
        """
        Authenticate with Supabase using password grant flow.

        Returns the access token on success.
        Raises AuthenticationError on failure.
        """
        if not self.supabase_url or not self.runner_email or not self.runner_password:
            raise AuthenticationError("Missing authentication configuration")

        auth_url = f"{self.supabase_url.rstrip('/')}/auth/v1/token?grant_type=password"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    auth_url,
                    headers={
                        "Content-Type": "application/json",
                        "apikey": self.supabase_anon_key,
                    },
                    json={
                        "email": self.runner_email,
                        "password": self.runner_password,
                    },
                )

                if response.status_code == 400:
                    error_data = response.json()
                    raise AuthenticationError(
                        f"Auth failed: {error_data.get('error_description', 'Invalid credentials')}"
                    )

                response.raise_for_status()
                data = response.json()

                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token")
                expires_in = data.get("expires_in", 3600)
                self._token_expires_at = time.time() + expires_in

                logger.info(
                    f"Authenticated successfully, token expires in {expires_in}s"
                )
                assert self._access_token is not None
                return self._access_token

        except httpx.HTTPStatusError as e:
            raise AuthenticationError(
                f"Authentication request failed: {e.response.status_code}"
            ) from e
        except Exception as e:
            raise AuthenticationError(f"Authentication error: {e}") from e

    def _refresh_auth_token(self) -> str:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            return self._authenticate()

        refresh_url = (
            f"{self.supabase_url.rstrip('/')}/auth/v1/token?grant_type=refresh_token"
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    refresh_url,
                    headers={
                        "Content-Type": "application/json",
                        "apikey": self.supabase_anon_key,
                    },
                    json={"refresh_token": self._refresh_token},
                )

                if response.status_code >= 400:
                    logger.warning("Token refresh failed, re-authenticating")
                    return self._authenticate()

                data = response.json()
                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                expires_in = data.get("expires_in", 3600)
                self._token_expires_at = time.time() + expires_in

                logger.debug(f"Token refreshed, expires in {expires_in}s")
                assert self._access_token is not None
                return self._access_token

        except Exception as e:
            logger.warning(f"Token refresh error: {e}, re-authenticating")
            return self._authenticate()

    def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if needed."""
        if self._access_token is not None and time.time() < (
            self._token_expires_at - TOKEN_REFRESH_BUFFER_SECONDS
        ):
            return self._access_token

        if self._refresh_token and time.time() < self._token_expires_at:
            return self._refresh_auth_token()

        return self._authenticate()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: str | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated HTTP request."""
        url = f"{self.api_url.rstrip('/')}{endpoint}"
        token = self._ensure_valid_token()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        with httpx.Client(timeout=self.timeout) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, content=payload)

            if response.status_code == 401:
                logger.warning("Got 401, re-authenticating and retrying")
                self._access_token = None
                token = self._ensure_valid_token()
                headers["Authorization"] = f"Bearer {token}"

                if method.upper() == "GET":
                    response = client.get(url, headers=headers)
                else:
                    response = client.post(url, headers=headers, content=payload)

            response.raise_for_status()
            return response.json()

    def get_job_config(self, job_id: str) -> JobConfig | None:
        """Fetch job details and scraper configurations from the coordinator."""
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return None

        try:
            data = self._make_request("GET", f"/api/scraper/v1/job?job_id={job_id}")

            scrapers = [
                ScraperConfig(
                    name=s.get("name", ""),
                    disabled=s.get("disabled", False),
                    base_url=s.get("base_url"),
                    search_url_template=s.get("search_url_template"),
                    selectors=s.get("selectors"),
                    options=s.get("options"),
                    test_skus=s.get("test_skus"),
                )
                for s in data.get("scrapers", [])
            ]

            return JobConfig(
                job_id=data["job_id"],
                skus=data.get("skus", []),
                scrapers=scrapers,
                test_mode=data.get("test_mode", False),
                max_workers=data.get("max_workers", 3),
            )

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to fetch job config: {e.response.status_code} - {e.response.text}"
            )
            return None
        except Exception as e:
            logger.error(f"Error fetching job config: {e}")
            return None

    def submit_results(
        self,
        job_id: str,
        status: str,
        runner_name: str | None = None,
        results: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Submit scrape results to the callback endpoint."""
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return False

        payload_dict: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "runner_name": runner_name or self.runner_name,
        }

        if results:
            payload_dict["results"] = results
        if error_message:
            payload_dict["error_message"] = error_message

        payload = json.dumps(payload_dict)

        try:
            self._make_request("POST", "/api/admin/scraping/callback", payload=payload)
            logger.info(f"Submitted results for job {job_id}: status={status}")
            return True

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to submit results: {e.response.status_code} - {e.response.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Error submitting results: {e}")
            return False

    def update_status(
        self, job_id: str, status: str, runner_name: str | None = None
    ) -> bool:
        """Send a status update (e.g., 'running') without results."""
        return self.submit_results(job_id, status, runner_name=runner_name)


api_client = ScraperAPIClient()
