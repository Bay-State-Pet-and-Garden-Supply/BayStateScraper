# send_logs() Integration Learnings

## Overview
Integrated log sending into `BayStateScraper/runner.py` to capture and send logs during job execution.

## Key Changes

### 1. Log Buffering Infrastructure
- Added `create_log_entry(level, message)` helper function that creates log entries in API-compatible format:
  ```python
  {
      "level": "debug|info|warning|error|critical",
      "message": "string",
      "timestamp": "ISO8601-string"
  }
  ```
- Uses `client.post_logs(job_id, log_buffer)` from `core.api_client` to send logs

### 2. Modified `run_job()` Function
- Added optional `log_buffer` parameter (list[dict] | None)
- Initializes buffer if not provided: `log_buffer = []`
- Captures logs at key execution points:
  - Job start
  - Configuration loading (success/failure)
  - No SKUs warning
  - Scraper execution start
  - SKU processing results (success/no_data/workflow_failed)
  - Job completion

### 3. Updated `run_full_mode()` Function
- Initializes log buffer: `log_buffer: list[dict] = []`
- Passes buffer to `run_job()`: `run_job(job_config, runner_name=runner_name, log_buffer=log_buffer)`
- Sends logs on successful completion: `client.post_logs(job_id, log_buffer)`
- Sends logs on error (before exit): `client.post_logs(job_id, log_buffer)`

## Log Entry Points
1. **Job Start**: "Job {job_id} started"
2. **SKU/Scraper Info**: "{count} SKUs with {count} scrapers"
3. **Config Loading**: "Loaded scraper config: {name}"
4. **Config Errors**: "Failed to parse config for {name}: {error}"
5. **Test Mode**: "Test mode: using {count} test SKUs from configs"
6. **No SKUs**: "No SKUs to process"
7. **Scraper Start**: "Starting scraper: {name}"
8. **SKU Results**: "{scraper}/{sku}: Found data" / "No data found"
9. **Workflow Failures**: "{scraper}/{sku}: Workflow failed"
10. **Execution Errors**: "{scraper}/{sku}: {ErrorType} - {message}"
11. **Init Failures**: "Failed to initialize {scraper}: {error}"
12. **Job Complete**: "Job complete. Processed {count} SKUs"

## Error Handling
- Logs are sent on error paths (configuration errors, API failures, job failures)
- `client.post_logs()` returns bool - failures are logged but don't interrupt execution
- Buffer is passed by reference, accumulating logs throughout job execution

## Important Note
The core API client uses `post_logs()` method, while the scraper_backend version uses `send_logs()`. Since runner.py imports from `core.api_client`, it uses `post_logs()`.

## Testing
- Python syntax verified: `python -m py_compile runner.py` ✓
- Import verification: `from runner import run_job, create_log_entry` ✓
