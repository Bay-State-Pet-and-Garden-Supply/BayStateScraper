"""
HTTP API client for communicating with BayStateApp coordinator.

This replaces direct Supabase access, ensuring runners have NO database credentials.
All communication is done via authenticated HTTP endpoints.
"""

import hashlib
import hmac
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


class ScraperAPIClient:
    """
    HTTP client for communicating with the BayStateApp coordinator API.

    Handles:
    - Fetching job configurations and scraper configs
    - Submitting scrape results
    - Status updates and heartbeats

    All requests are authenticated using HMAC-SHA256 signatures.
    """

    def __init__(
        self,
        api_url: str | None = None,
        webhook_secret: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the API client.

        Args:
            api_url: Base URL for the coordinator API (e.g., https://app.example.com)
            webhook_secret: Secret key for HMAC signatures
            timeout: HTTP request timeout in seconds
        """
        self.api_url = api_url or os.environ.get("SCRAPER_API_URL", "")
        self.webhook_secret = webhook_secret or os.environ.get("SCRAPER_WEBHOOK_SECRET", "")
        self.runner_name = os.environ.get("RUNNER_NAME", "unknown-runner")
        self.timeout = timeout

        if not self.api_url:
            logger.warning("SCRAPER_API_URL not configured")
        if not self.webhook_secret:
            logger.warning("SCRAPER_WEBHOOK_SECRET not configured")

    def _create_signature(self, payload: str) -> str:
        """Create HMAC-SHA256 signature for a payload."""
        return hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: str | None = None,
        sign_payload: str | None = None,
    ) -> dict[str, Any]:
        """
        Make an authenticated HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            payload: Request body for POST requests
            sign_payload: String to sign (defaults to payload for POST, or query param for GET)

        Returns:
            Parsed JSON response

        Raises:
            httpx.HTTPStatusError: For non-2xx responses
        """
        url = f"{self.api_url.rstrip('/')}{endpoint}"

        # Create signature
        signature_input = sign_payload or payload or ""
        signature = self._create_signature(signature_input)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
        }

        with httpx.Client(timeout=self.timeout) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, content=payload)

            response.raise_for_status()
            return response.json()

    def get_job_config(self, job_id: str) -> JobConfig | None:
        """
        Fetch job details and scraper configurations from the coordinator.

        Args:
            job_id: The UUID of the scrape job

        Returns:
            JobConfig with SKUs and scraper configurations, or None on error
        """
        if not self.api_url or not self.webhook_secret:
            logger.error("API client not configured - missing URL or secret")
            return None

        try:
            # Signature is computed on job_id for GET requests
            data = self._make_request(
                "GET",
                f"/api/scraper/v1/job?job_id={job_id}",
                sign_payload=job_id,
            )

            # Parse scrapers
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

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch job config: {e.response.status_code} - {e.response.text}")
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
        """
        Submit scrape results to the callback endpoint.

        Args:
            job_id: The job identifier
            status: Job status ('running', 'completed', 'failed')
            runner_name: Optional runner identifier
            results: Scraping results data
            error_message: Error message if status is 'failed'

        Returns:
            True if successful, False otherwise
        """
        if not self.api_url or not self.webhook_secret:
            logger.error("API client not configured - missing URL or secret")
            return False

        payload_dict: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
        }

        if runner_name:
            payload_dict["runner_name"] = runner_name
        else:
            payload_dict["runner_name"] = self.runner_name
        if results:
            payload_dict["results"] = results
        if error_message:
            payload_dict["error_message"] = error_message

        payload = json.dumps(payload_dict)

        try:
            self._make_request(
                "POST",
                "/api/admin/scraping/callback",
                payload=payload,
            )
            logger.info(f"Submitted results for job {job_id}: status={status}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to submit results: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Error submitting results: {e}")
            return False

    def update_status(self, job_id: str, status: str, runner_name: str | None = None) -> bool:
        """
        Send a status update (e.g., 'running') without results.

        Args:
            job_id: The job identifier
            status: Current status
            runner_name: Optional runner identifier

        Returns:
            True if successful
        """
        return self.submit_results(job_id, status, runner_name=runner_name)


# Global singleton for convenience
api_client = ScraperAPIClient()
