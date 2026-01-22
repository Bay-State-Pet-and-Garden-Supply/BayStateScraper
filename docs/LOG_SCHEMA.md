# BayStateScraper JSON Log Schema

This document defines the canonical JSON log schema for BayStateScraper. All logs should conform to this schema for consistent parsing and ingestion by BayStateApp.

## Overview

All log entries must be valid JSON objects emitted as a single line (no pretty-printing) to stdout. This format is designed for:
- Docker log collection (stdout → container logs)
- Log aggregation pipelines
- Machine parsing and search
- Correlation across job/scraper/sku/step

## Field Definitions

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `timestamp` | string | ISO 8601 timestamp with timezone | `"2026-01-22T00:48:56.703Z"` |
| `level` | string | Log severity level (uppercase) | `"INFO"`, `"WARNING"`, `"ERROR"`, `"DEBUG"` |
| `logger` | string | Module name that emitted the log | `"daemon"`, `"runner"`, `"workflow_executor"` |
| `message` | string | Human-readable log message | `"Starting job 12345"` |
| `job_id` | string | Unique identifier for the scraping job | `"550e8400-e29b-41d4-a716-446655440000"` |
| `runner_name` | string | Identifier for this runner instance | `"baystate-runner-01"` |

### Optional Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `scraper_name` | string | Name of the scraper being executed | `"amazon"`, `"walmart"` |
| `sku` | string | SKU being processed | `"ABC123"` |
| `step` | string | Current workflow step/action name | `"extract"`, `"navigate"` |
| `worker_id` | string | Worker identifier for parallel execution | `"worker-1"` |
| `error_type` | string | Exception class name (ERROR/EXCEPTION logs) | `"ScraperError"`, `"TimeoutError"` |
| `error_message` | string | Exception message (ERROR/EXCEPTION logs) | `"Selector not found: .product-title"` |
| `stack_trace` | string | Full stack trace (ERROR/EXCEPTION logs) | *(multi-line string, should be single line or escaped)* |
| `duration_ms` | number | Duration in milliseconds (performance logs) | `1250.5` |

### Reserved Fields (Do Not Use)

The following field names are reserved for future use:
- `correlation_id` (use `job_id`)
- `trace_id`, `span_id` (future distributed tracing)
- `version` (schema version)

## Example Log Lines

### INFO - Job Start

```json
{"timestamp":"2026-01-22T00:48:56.703Z","level":"INFO","logger":"runner","message":"Starting job 550e8400-e29b-41d4-a716-446655440000","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","scraper_name":"amazon","skus":5}
```

### INFO - SKU Processing

```json
{"timestamp":"2026-01-22T00:48:57.891Z","level":"INFO","logger":"workflow_executor","message":"Processing SKU ABC123","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","scraper_name":"amazon","sku":"ABC123","step":"extract"}
```

### DEBUG - Workflow Step

```json
{"timestamp":"2026-01-22T00:49:01.234Z","level":"DEBUG","logger":"workflow_executor","message":"Step navigate completed","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","scraper_name":"amazon","sku":"ABC123","step":"navigate","duration_ms":450.2}
```

### WARNING - Extraction Issue

```json
{"timestamp":"2026-01-22T00:49:02.567Z","level":"WARNING","logger":"extract_handler","message":"Field 'price' not found, using default","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","scraper_name":"amazon","sku":"ABC123","step":"extract"}
```

### ERROR - Critical Failure

```json
{"timestamp":"2026-01-22T00:49:05.891Z","level":"ERROR","logger":"workflow_executor","message":"Workflow failed for SKU ABC123","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","scraper_name":"amazon","sku":"ABC123","error_type":"ScraperError","error_message":"CAPTCHA detected: please solve manually","stack_trace":"Traceback (most recent call last):\n  File \"workflow_executor.py\", line 156, in execute_workflow\n    ...\nScraperError: CAPTCHA detected: please solve manually"}
```

### ERROR - Exception with Duration

```json
{"timestamp":"2026-01-22T00:49:10.123Z","level":"ERROR","logger":"api_client","message":"Failed to submit results","job_id":"550e8400-e29b-41d4-a716-446655440000","runner_name":"baystate-runner-01","error_type":"httpx.ConnectError","error_message":"Connection refused","duration_ms":30000.0}
```

## Redaction Rules

### Never Log

The following must **never** be logged:
- API keys, tokens, passwords
- Cookie values
- Authorization headers
- Credit card numbers or payment info
- Full HTML page content
- Session identifiers
- User email addresses or PII

### Sanitize

If the following data must be logged, sanitize it first:
- URLs (remove query parameters that may contain tokens)
- Form inputs (mask password fields)
- Response bodies (truncate large responses)

### Example: Sanitized URL

**Bad:**
```json
{"message":"Requesting URL","url":"https://api.example.com/users?api_key=secret123"}
```

**Good:**
```json
{"message":"Requesting URL","url":"https://api.example.com/users?api_key=[REDACTED]"}
```

## Implementation Notes

### Using Python Standard Library

The schema can be implemented using Python's `logging` module with a custom JSON formatter:

```python
import json
import logging
from datetime import datetime, timezone

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "job_id": getattr(record, "job_id", ""),
            "runner_name": getattr(record, "runner_name", ""),
        }
        # Add optional fields if present
        if hasattr(record, "scraper_name") and record.scraper_name:
            log_data["scraper_name"] = record.scraper_name
        # ... more optional fields
        
        return json.dumps(log_data)
```

### Context Injection

For injecting job/scraper/sku context, prefer:
1. `contextvars` module with a custom formatter
2. `logging.LoggerAdapter` for per-call context
3. `logging.setLogRecordFactory()` for per-record attributes

### Log Levels

| Level | Use Case |
|-------|----------|
| DEBUG | Detailed debug info (step execution, selectors, timing) |
| INFO | Normal operation (job start/stop, SKU processing, workflow progress) |
| WARNING | Unexpected but recoverable (missing optional data, retries) |
| ERROR | Failures that need attention (extraction errors, API failures) |
| CRITICAL | System-level failures (database connection, memory exhaustion) |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-22 | Initial schema definition |

