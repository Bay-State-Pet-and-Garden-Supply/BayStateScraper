"""
HTTP API client for communicating with BayStateApp coordinator.

Uses simple API Key authentication - no token refresh, no password management.
Runners authenticate with a single API key issued from the admin panel.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
    - API Key authentication (X-API-Key header)
    - Fetching job configurations and scraper configs
    - Submitting scrape results
    - Status updates and heartbeats
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        runner_name: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_url = api_url or os.environ.get("SCRAPER_API_URL", "")
        self.api_key = api_key or os.environ.get("SCRAPER_API_KEY", "")
        self.runner_name = runner_name or os.environ.get(
            "RUNNER_NAME", "unknown-runner"
        )
        self.timeout = timeout

        if not self.api_url:
            logger.warning("SCRAPER_API_URL not configured")
        if not self.api_key:
            logger.warning("SCRAPER_API_KEY not configured")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for authenticated requests."""
        if not self.api_key:
            raise AuthenticationError("SCRAPER_API_KEY not configured")

        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: str | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated HTTP request."""
        url = f"{self.api_url.rstrip('/')}{endpoint}"
        headers = self._get_headers()

        with httpx.Client(timeout=self.timeout) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, content=payload)

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key")

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


# Global instance for convenience
api_client = ScraperAPIClient()
