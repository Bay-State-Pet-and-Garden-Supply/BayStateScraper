"""
Local request queue implementation using JSON file storage.
"""

from __future__ import annotations


import json
import uuid
from pathlib import Path
from typing import Any


class LocalRequestQueue:
    """
    Local file-based request queue.

    Stores pending and handled requests in JSON files.
    """

    def __init__(self, queue_id: str, base_dir: str):
        """
        Initialize the request queue.

        Args:
            queue_id: Unique identifier for the queue
            base_dir: Base directory for storage
        """
        self.queue_id = queue_id
        self.base_dir = Path(base_dir)
        self.storage_dir = self.base_dir / queue_id
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.pending_file = self.storage_dir / "pending.json"
        self.handled_file = self.storage_dir / "handled.json"

        self._pending_requests: list[dict[str, Any]] = []
        self._handled_requests: list[dict[str, Any]] = []
        self._load_requests()

    def _load_requests(self):
        """Load existing requests from storage files."""
        # Load pending requests
        if self.pending_file.exists():
            try:
                with open(self.pending_file, encoding="utf-8") as f:
                    data: dict[str, Any] = json.load(f)
                    self._pending_requests = data.get("requests", [])
            except (OSError, json.JSONDecodeError):
                self._pending_requests = []
        else:
            self._pending_requests = []

        # Load handled requests
        if self.handled_file.exists():
            try:
                with open(self.handled_file, encoding="utf-8") as f:
                    data_handled: dict[str, Any] = json.load(f)
                    self._handled_requests = data_handled.get("requests", [])
            except (OSError, json.JSONDecodeError):
                self._handled_requests = []
        else:
            self._handled_requests = []

    def _save_pending(self):
        """Save pending requests to file."""
        with open(self.pending_file, "w", encoding="utf-8") as f:
            json.dump({"requests": self._pending_requests}, f, ensure_ascii=False, indent=2)

    def _save_handled(self):
        """Save handled requests to file."""
        with open(self.handled_file, "w", encoding="utf-8") as f:
            json.dump({"requests": self._handled_requests}, f, ensure_ascii=False, indent=2)

    def add_request(self, request: dict[str, Any]) -> str:
        """
        Add a request to the queue.

        Args:
            request: The request data

        Returns:
            Unique request ID
        """
        request_id = f"req_{uuid.uuid4().hex[:8]}"
        self._pending_requests.append(request)
        self._save_pending()
        return request_id

    def fetch_next_request(self) -> dict[str, Any] | None:
        """
        Fetch the next pending request.

        Returns:
            The next request or None if queue is empty
        """
        if not self._pending_requests:
            return None

        request = self._pending_requests.pop(0)
        self._save_pending()
        return request

    def mark_request_as_handled(self, request: dict[str, Any]):
        """
        Mark a request as handled.

        Args:
            request: The request returned by fetch_next_request
        """
        self._handled_requests.append(request)
        self._save_handled()

    def reclaim_request(self, request: dict[str, Any]):
        """
        Reclaim a handled request back to pending.

        Args:
            request: The request to reclaim
        """
        # Remove from handled (assuming requests are unique for this test)
        if request in self._handled_requests:
            self._handled_requests.remove(request)
            self._save_handled()

            # Add back to pending
            self._pending_requests.append(request)
            self._save_pending()

    def get_info(self) -> dict[str, Any]:
        """
        Get queue information.

        Returns:
            Dictionary with queue info
        """
        return {
            "id": self.queue_id,
            "pendingRequestCount": len(self._pending_requests),
            "handledRequestCount": len(self._handled_requests),
            "totalRequestCount": len(self._pending_requests) + len(self._handled_requests),
        }

    def drop(self):
        """Drop the queue and delete all data."""
        if self.pending_file.exists():
            self.pending_file.unlink()
        if self.handled_file.exists():
            self.handled_file.unlink()
        self._pending_requests = []
        self._handled_requests = []

    def is_empty(self) -> bool:
        """Check if the queue has no pending requests."""
        return len(self._pending_requests) == 0

    def __len__(self) -> int:
        """Return the number of pending requests."""
        return len(self._pending_requests)
