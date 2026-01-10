import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.api_client import ScraperAPIClient


class ScraperAPIHandler(logging.Handler):
    """
    Logging handler that sends logs to the BayStateApp API.

    Buffers logs and sends them in batches to reduce API overhead.
    """

    def __init__(self, api_client: "ScraperAPIClient", job_id: str, buffer_size: int = 20, flush_interval: float = 2.0):
        super().__init__()
        self.api_client = api_client
        self.job_id = job_id
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval

        self._buffer: list[dict[str, Any]] = []
        self._last_flush_time = time.time()

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record.

        If the buffer is full or time has elapsed, flush the buffer.
        """
        try:
            msg = self.format(record)
            log_entry = {"level": record.levelname, "message": msg, "timestamp": datetime.fromtimestamp(record.created).isoformat()}

            self._buffer.append(log_entry)

            should_flush = len(self._buffer) >= self.buffer_size or (time.time() - self._last_flush_time) >= self.flush_interval

            if should_flush:
                self.flush()

        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        """
        Flush the buffer to the API.
        """
        self.acquire()
        try:
            if not self._buffer:
                return

            logs_to_send = list(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.time()
        finally:
            self.release()

        # Send outside lock to avoid blocking other logging calls
        try:
            self.api_client.post_logs(self.job_id, logs_to_send)
        except Exception:
            # We can't use self.handleError easily without a record,
            # but logging.Handler.handleError handles None record in some versions or we construct a dummy.
            # Actually, standard practice is to just print to stderr if logging fails to prevent recursion.
            import sys

            sys.stderr.write(f"Failed to flush logs to API: {sys.exc_info()[1]}\n")
