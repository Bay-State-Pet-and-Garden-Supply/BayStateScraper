import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DebugContext:
    """
    Manages debug context for scraper jobs.
    Stores logs, page sources, and screenshots in memory (and potentially disk).
    """

    def __init__(self):
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_job_id: str | None = None

    def start_session(self, job_id: str, debug_mode: bool = False):
        """Start a new debug session."""
        with self._lock:
            self._sessions[job_id] = {
                "job_id": job_id,
                "start_time": datetime.now(),
                "end_time": None,
                "debug_mode": debug_mode,
                "logs": [],
                "page_sources": [],  # List of {timestamp, sku, source}
                "screenshots": [],   # List of {timestamp, sku, base64}
                "current_page_source": None,
                "current_screenshot": None,
            }
            self._last_job_id = job_id

    def end_session(self, job_id: str):
        """End a debug session."""
        with self._lock:
            if job_id in self._sessions:
                self._sessions[job_id]["end_time"] = datetime.now()

    def log(self, job_id: str, message: str):
        """Add a log message to the session."""
        with self._lock:
            session = self._sessions.get(job_id)
            if session:
                entry = {
                    "timestamp": datetime.now().isoformat(),
                    "message": message
                }
                session["logs"].append(entry)

    def capture_snapshot(self, job_id: str, sku: str, page_source: str | None = None, screenshot: str | None = None):
        """Capture a snapshot (source/screenshot) for a SKU."""
        with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return

            timestamp = datetime.now().isoformat()
            
            if page_source:
                session["page_sources"].append({
                    "timestamp": timestamp,
                    "sku": sku,
                    "content": page_source
                })
                session["current_page_source"] = page_source
            
            if screenshot:
                session["screenshots"].append({
                    "timestamp": timestamp,
                    "sku": sku,
                    "content": screenshot
                })
                session["current_screenshot"] = screenshot

    def _resolve_job_id(self, job_id: str | None) -> str | None:
        """Resolve 'last' or None to the actual job ID."""
        if job_id == "last" or job_id is None:
            return self._last_job_id
        return job_id

    def get_session_info(self, job_id: str | None = None) -> dict[str, Any] | None:
        """Get high-level info about a session."""
        actual_job_id = self._resolve_job_id(job_id)
        if not actual_job_id:
            return None

        with self._lock:
            session = self._sessions.get(actual_job_id)
            if not session:
                return None
            
            # Return summary (exclude heavy content)
            return {
                "job_id": session["job_id"],
                "start_time": session["start_time"].isoformat() if session["start_time"] else None,
                "end_time": session["end_time"].isoformat() if session["end_time"] else None,
                "debug_mode": session["debug_mode"],
                "log_count": len(session["logs"]),
                "snapshot_count": len(session["page_sources"]),
            }

    def get_current_page_source(self, job_id: str | None = None) -> str | None:
        """Get the most recent page source."""
        actual_job_id = self._resolve_job_id(job_id)
        if not actual_job_id:
            return None
            
        with self._lock:
            session = self._sessions.get(actual_job_id)
            return session.get("current_page_source") if session else None

    def get_current_screenshot(self, job_id: str | None = None) -> str | None:
        """Get the most recent screenshot."""
        actual_job_id = self._resolve_job_id(job_id)
        if not actual_job_id:
            return None
            
        with self._lock:
            session = self._sessions.get(actual_job_id)
            return session.get("current_screenshot") if session else None

    def get_verbose_logs(self, job_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get logs for a session."""
        actual_job_id = self._resolve_job_id(job_id)
        if not actual_job_id:
            return []

        with self._lock:
            session = self._sessions.get(actual_job_id)
            if not session:
                return []
            return list(session["logs"][-limit:])

    def get_snapshots(self, job_id: str | None = None, sku: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get snapshots (metadata only)."""
        actual_job_id = self._resolve_job_id(job_id)
        if not actual_job_id:
            return []

        with self._lock:
            session = self._sessions.get(actual_job_id)
            if not session:
                return []
            
            # Combine sources and screenshots
            snapshots = []
            # This is a bit simplified; in reality we might want to pair them up
            # For now just return page sources as the primary "snapshot" list
            for src in session["page_sources"]:
                if sku and src["sku"] != sku:
                    continue
                snapshots.append({
                    "type": "html",
                    "timestamp": src["timestamp"],
                    "sku": src["sku"],
                    "length": len(src["content"])
                })
            
            # Add screenshots too?
            for screen in session["screenshots"]:
                 if sku and screen["sku"] != sku:
                    continue
                 snapshots.append({
                    "type": "screenshot",
                    "timestamp": screen["timestamp"],
                    "sku": screen["sku"],
                    "length": len(screen["content"])
                 })
                 
            # Sort by timestamp desc and limit
            snapshots.sort(key=lambda x: x["timestamp"], reverse=True)
            return snapshots[:limit]


# Global instance
debug_context = DebugContext()
