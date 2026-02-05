"""
HTTP API client for communicating with BayStateApp coordinator.

Uses simple API Key authentication - no token refresh, no password management.
Runners authenticate with a single API key issued from the admin panel.
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

# Retry configuration constants
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_MULTIPLIER = 2  # Exponential backoff: 1s, 2s, 4s, 8s
RETRY_INITIAL_DELAY = 1.0  # Initial delay in seconds


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


class ConnectionError(Exception):
    """Raised when API connection fails."""

    pass


def _is_retryable_error(status_code: int | None, exception: Exception) -> bool:
    """
    Determine if an error is retryable based on HTTP status code and exception type.

    Args:
        status_code: HTTP status code (None if no response received)
        exception: The exception that was raised

    Returns:
        True if the error should be retried, False otherwise
    """
    # Network errors, timeouts, and connection issues are retryable
    if isinstance(exception, (httpx.NetworkError, httpx.TimeoutException)):
        return True

    # 5xx server errors are retryable
    if status_code is not None and 500 <= status_code < 600:
        return True

    # 429 Too Many Requests (rate limiting) is retryable
    if status_code == 429:
        return True

    # 4xx client errors are NOT retryable (except 401 which is handled separately)
    if status_code is not None and 400 <= status_code < 500:
        return False

    # For any other case, be conservative and allow retry
    return True


class ScraperAPIClient:
    """
    HTTP client for communicating with the BayStateApp coordinator API.

    Handles:
    - API Key authentication (X-API-Key header)
    - Fetching job configurations and scraper configs
    - Submitting scrape results
    - Status updates and heartbeats
    - Retry logic with exponential backoff for transient failures
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        runner_name: str | None = None,
        timeout: float = 30.0,
        max_retries: int | None = None,
    ):
        self.api_url = api_url or os.environ.get("SCRAPER_API_URL", "")
        self.api_key = api_key or os.environ.get("SCRAPER_API_KEY", "")
        self.runner_name = runner_name or os.environ.get("RUNNER_NAME", "unknown-runner")
        self.timeout = timeout
        self.max_retries = max_retries if max_retries is not None else int(os.environ.get("SCRAPER_API_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))

        if not self.api_url:
            logger.warning("SCRAPER_API_URL not configured")
        if not self.api_key:
            logger.warning("SCRAPER_API_KEY not configured")

    def health_check(self) -> bool:
        """
        Perform a quick health check to verify API connectivity.

        This method makes a lightweight GET request to verify the API is reachable
        and responding. It does NOT use retry logic - it's intended as a quick
        connectivity check before job execution.

        Returns:
            True if API is healthy and responding, False otherwise.

        Raises:
            ConnectionError: If the API is unreachable or returns an error.
        """
        if not self.api_url:
            error_msg = "Cannot perform health check: SCRAPER_API_URL not configured"
            logger.error(f"[API Client] {error_msg}")
            raise ConnectionError(error_msg)

        health_url = f"{self.api_url.rstrip('/')}/api/health"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(health_url, headers=self._get_headers())

                if response.status_code == 200:
                    logger.info(f"[API Client] Health check passed: {self.api_url}")
                    return True
                else:
                    error_msg = f"Health check failed: API returned status {response.status_code} (expected 200 OK)"
                    logger.error(f"[API Client] {error_msg}")
                    raise ConnectionError(error_msg)

        except httpx.NetworkError as e:
            error_msg = f"Health check failed: Network error - {str(e)}"
            logger.error(f"[API Client] {error_msg}")
            raise ConnectionError(error_msg)
        except httpx.TimeoutException as e:
            error_msg = f"Health check failed: Request timed out ({self.timeout}s) - {str(e)}"
            logger.error(f"[API Client] {error_msg}")
            raise ConnectionError(error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"Health check failed: HTTP error {e.response.status_code} - {str(e)}"
            logger.error(f"[API Client] {error_msg}")
            raise ConnectionError(error_msg)
        except Exception as e:
            error_msg = f"Health check failed: Unexpected error - {str(e)}"
            logger.error(f"[API Client] {error_msg}")
            raise ConnectionError(error_msg)

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
        """
        Make an authenticated HTTP request with retry logic and exponential backoff.

        Retries on transient failures (network errors, timeouts, 5xx errors).
        Fails immediately on non-retryable errors (4xx client errors, auth failures).
        """
        url = f"{self.api_url.rstrip('/')}{endpoint}"
        headers = self._get_headers()

        last_exception: Exception | None = None
        delay = RETRY_INITIAL_DELAY

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    if method.upper() == "GET":
                        response = client.get(url, headers=headers)
                    else:
                        response = client.post(url, headers=headers, content=payload)

                    # Authentication failure - not retryable
                    if response.status_code == 401:
                        raise AuthenticationError("Invalid API key")

                    # Raise for status on HTTP errors
                    response.raise_for_status()
                    return response.json()

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                is_retryable = _is_retryable_error(status_code, e)

                if not is_retryable or attempt >= self.max_retries:
                    # Non-retryable error or max retries exceeded
                    raise

                last_exception = e
                logger.warning(
                    f"API request failed (attempt {attempt + 1}/{self.max_retries + 1}): {status_code} - {e.response.text[:200]}. Retrying in {delay:.1f}s..."
                )

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt >= self.max_retries:
                    raise

                last_exception = e
                logger.warning(
                    f"API request failed (attempt {attempt + 1}/{self.max_retries + 1}): {type(e).__name__} - {str(e)[:200]}. Retrying in {delay:.1f}s..."
                )

            except Exception as e:
                # Other exceptions (e.g., JSON decode errors) - not retryable
                raise

            # Wait before retrying with exponential backoff
            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= RETRY_BACKOFF_MULTIPLIER

        # This should not be reached, but just in case
        if last_exception:
            raise last_exception
        raise Exception("Unexpected error in retry loop")

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

        except (httpx.HTTPError, AuthenticationError) as e:
            # Specific HTTP and authentication exceptions from _make_request
            logger.exception(f"Failed to send logs for job {job_id}")
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
