"""
HTTP API client for communicating with BayStateApp coordinator.

Uses simple API Key authentication - no token refresh, no password management.
Runners authenticate with a single API key issued from the admin panel.
"""

from __future__ import annotations

import logging
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
        self.runner_name = runner_name or os.environ.get("RUNNER_NAME", "unknown-runner")
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
            logger.error(f"Failed to submit results: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Error submitting results: {e}")
            return False

    def update_status(self, job_id: str, status: str, runner_name: str | None = None) -> bool:
        """Send a status update (e.g., 'running') without results."""
        return self.submit_results(job_id, status, runner_name=runner_name)

    def claim_chunk(self, job_id: str, runner_name: str | None = None) -> dict[str, Any] | None:
        """
        Claim the next available chunk for processing.

        Returns chunk data with keys: chunk_id, chunk_index, skus, scrapers
        Returns None if no chunks are available.
        """
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return None

        payload = json.dumps(
            {
                "job_id": job_id,
                "runner_name": runner_name or self.runner_name,
            }
        )

        try:
            data = self._make_request("POST", "/api/scraper/v1/claim-chunk", payload=payload)

            chunk = data.get("chunk")
            if not chunk:
                logger.info(f"No pending chunks for job {job_id}")
                return None

            logger.info(f"Claimed chunk {chunk.get('chunk_index')} with {len(chunk.get('skus', []))} SKUs")
            return chunk

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to claim chunk: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error claiming chunk: {e}")
            return None

    def submit_chunk_results(
        self,
        chunk_id: str,
        status: str,
        results: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Submit results for a completed chunk."""
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return False

        payload_dict: dict[str, Any] = {
            "chunk_id": chunk_id,
            "status": status,
            "runner_name": self.runner_name,
        }

        if results:
            payload_dict["results"] = results
        if error_message:
            payload_dict["error_message"] = error_message

        payload = json.dumps(payload_dict)

        try:
            self._make_request("POST", "/api/scraper/v1/chunk-callback", payload=payload)
            logger.info(f"Submitted results for chunk {chunk_id}: status={status}")
            return True

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to submit chunk results: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Error submitting chunk results: {e}")
            return False

    def poll_for_work(self) -> JobConfig | None:
        """
        Poll the coordinator for the next available job.

        This is the primary method for daemon mode - the runner continuously
        polls this endpoint to claim work. The coordinator uses FOR UPDATE
        SKIP LOCKED to ensure atomic job claiming across multiple runners.

        Returns:
            JobConfig if a job was claimed, None if no work available.
        """
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return None

        payload = json.dumps(
            {
                "runner_name": self.runner_name,
            }
        )

        try:
            data = self._make_request("POST", "/api/scraper/v1/poll", payload=payload)

            job_data = data.get("job")
            if not job_data:
                logger.debug("No pending jobs available")
                return None

            # Parse scrapers from response
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
                for s in job_data.get("scrapers", [])
            ]

            job = JobConfig(
                job_id=job_data["job_id"],
                skus=job_data.get("skus", []),
                scrapers=scrapers,
                test_mode=job_data.get("test_mode", False),
                max_workers=job_data.get("max_workers", 3),
            )

            logger.info(f"Claimed job {job.job_id} with {len(job.skus)} SKUs")
            return job

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # 404 means no jobs available - not an error
                logger.debug("No pending jobs (404)")
                return None
            logger.error(f"Failed to poll for work: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error polling for work: {e}")
            return None

    def heartbeat(self) -> bool:
        """
        Send a heartbeat to the coordinator to indicate the runner is alive.

        The coordinator uses heartbeats to track runner health. If a runner
        misses too many heartbeats (e.g., 5 minutes), it's marked as lost
        and any in-progress jobs may be re-queued.

        Returns:
            True if heartbeat was acknowledged, False on error.
        """
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return False

        payload = json.dumps(
            {
                "runner_name": self.runner_name,
            }
        )

        try:
            self._make_request("POST", "/api/scraper/v1/heartbeat", payload=payload)
            logger.debug(f"Heartbeat sent for {self.runner_name}")
            return True

        except AuthenticationError as e:
            logger.error(f"Heartbeat auth failed: {e}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Heartbeat failed: {e.response.status_code} - {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return False

    def post_logs(self, job_id: str, logs: list[dict[str, Any]]) -> bool:
        """
        Send a batch of logs to the API.

        Note: This method intentionally avoids using self.logger to prevent
        infinite recursion loops since this client is used by the logging handler.
        """
        if not self.api_url:
            return False

        payload = json.dumps({"job_id": job_id, "logs": logs})

        try:
            self._make_request("POST", "/api/scraper/v1/logs", payload=payload)
            return True

        except Exception:
            # Allow exception to bubble up to the handler
            raise

    def get_credentials(self, scraper_name: str) -> dict[str, str] | None:
        """
        Fetch credentials for a specific scraper from the coordinator.

        Credentials are fetched on-demand and should NOT be stored locally.
        The coordinator returns credentials over HTTPS to authenticated runners.

        Args:
            scraper_name: Name of the scraper (e.g., "petfoodex", "phillips")

        Returns:
            Dict with 'username' and 'password' keys, or None if not available.
        """
        if not self.api_url:
            logger.error("API client not configured - missing URL")
            return None

        try:
            data = self._make_request("GET", f"/api/scraper/v1/credentials?scraper={scraper_name}")

            if data.get("username") and data.get("password"):
                logger.debug(f"Retrieved credentials for {scraper_name}")
                return {
                    "username": data["username"],
                    "password": data["password"],
                }

            logger.warning(f"No credentials available for {scraper_name}")
            return None

        except AuthenticationError as e:
            logger.error(f"Credentials auth failed: {e}")
            return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"No credentials configured for {scraper_name}")
                return None
            logger.error(f"Failed to fetch credentials: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error fetching credentials: {e}")
            return None


# Global instance for convenience
api_client = ScraperAPIClient()
