import atexit
import logging
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

# Try to get module name for logging
try:
    _module_name = __name__
except NameError:
    _module_name = "api_handler"


class ScraperAPIHandler(logging.Handler):
    """
    Logging handler that sends logs to the BayStateApp API.

    Features:
    - Bounded buffer with configurable size and flush interval
    - Non-blocking: uses a separate thread for shipping
    - Graceful shutdown: flushes buffer on exit
    - Retry with exponential backoff on transient failures
    - Drops logs on persistent failures to avoid memory growth
    """

    def __init__(
        self,
        api_client: Any,  # ScraperAPIClient type causes import issues at runtime
        job_id: str,
        buffer_size: int = 20,
        flush_interval: float = 2.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_queue_size: int = 1000,
    ):
        super().__init__()
        self.api_client = api_client
        self.job_id = job_id
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_queue_size = max_queue_size

        # Thread-safe buffer using deque
        self._buffer: deque = deque(maxlen=max_queue_size)
        self._last_flush_time = time.time()

        # Shipping thread control
        self._shipping_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._flush_event = threading.Event()

        # Start shipping thread
        self._start_shipping_thread()

        # Register cleanup on exit
        self._registered_atexit = False
        self._register_atexit()

    def _register_atexit(self) -> None:
        """Register atexit handler to ensure graceful flush."""
        try:
            atexit.register(self.close)
            self._registered_atexit = True
        except Exception:
            pass  # atexit may fail in some environments

    def _start_shipping_thread(self) -> None:
        """Start the background thread for shipping logs."""
        self._shipping_thread = threading.Thread(
            target=self._shipping_loop,
            daemon=True,
            name="log-shipping",
        )
        self._shipping_thread.start()

    def _shipping_loop(self) -> None:
        """Background loop that ships logs periodically."""
        while not self._stop_event.is_set():
            # Wait for flush event or timeout
            flush_waited = self._flush_event.wait(timeout=self.flush_interval)

            if self._stop_event.is_set():
                break

            # Flush if needed
            if self._buffer:
                self._ship_buffer()

            # Clear flush event
            if flush_waited:
                self._flush_event.clear()

    def _ship_buffer(self) -> None:
        """Ship the current buffer to the API with retry logic."""
        if not self._buffer:
            return

        # Copy buffer under lock
        with threading.Lock():
            if not self._buffer:
                return
            logs_to_send = list(self._buffer)
            self._buffer.clear()

        # Ship with retry
        self._send_with_retry(logs_to_send)
        self._last_flush_time = time.time()

    def _send_with_retry(self, logs: list) -> None:
        """Send logs with exponential backoff retry."""
        if not logs:
            return

        delay = self.retry_delay
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                self.api_client.post_logs(self.job_id, logs)
                return  # Success
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff

        # All retries exhausted - drop logs and warn
        try:
            sys.stderr.write(f"[{_module_name}] Failed to ship {len(logs)} logs after {self.max_retries} retries: {last_error}\n")
        except Exception:
            pass  # Best effort

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record by adding it to the buffer.

        This method is designed to be non-blocking.
        """
        try:
            # Format log entry with all context fields
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }

            # Add optional context fields from record
            for field in ["job_id", "runner_name", "scraper_name", "sku", "step", "worker_id"]:
                value = getattr(record, field, None)
                if value is not None and value != "":
                    log_entry[field] = value

            # Add error fields if present
            if record.exc_info:
                log_entry["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
                log_entry["error_message"] = str(record.exc_info[1]) if record.exc_info[1] else None

            # Add to buffer (non-blocking, uses deque with maxlen)
            try:
                self._buffer.append(log_entry)
            except IndexError:
                # Buffer full - drop oldest to make room
                try:
                    self._buffer.popleft()
                    self._buffer.append(log_entry)
                except IndexError:
                    pass  # Still full, drop this log

            # Signal shipping thread to check flush
            self._flush_event.set()

        except Exception:
            # Best effort - don't let logging failures affect scraper
            pass

    def flush(self) -> None:
        """
        Flush the buffer to the API.

        This method signals the shipping thread and waits briefly for completion.
        """
        self._flush_event.set()

        # Brief wait for shipping thread to process
        if self._shipping_thread and self._shipping_thread.is_alive():
            self._shipping_thread.join(timeout=0.5)

    def close(self) -> None:
        """
        Close the handler and flush all pending logs.

        This method is called on program exit to ensure no logs are lost.
        """
        if hasattr(self, "_stop_event"):
            # Signal shipping thread to stop
            self._stop_event.set()
            self._flush_event.set()

            # Wait for shipping thread to finish
            if self._shipping_thread and self._shipping_thread.is_alive():
                try:
                    self._shipping_thread.join(timeout=2.0)
                except Exception:
                    pass

            # Final flush attempt
            if self._buffer:
                try:
                    logs_to_send = list(self._buffer)
                    self._buffer.clear()
                    self._send_with_retry(logs_to_send)
                except Exception:
                    pass

        # Call parent close
        super().close()

    def __del__(self) -> None:
        """Ensure cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass
