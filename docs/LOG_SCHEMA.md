# JSON Log Schema

All logs in BayStateScraper are emitted as single-line JSON objects to stdout. This schema ensures compatibility with downstream observability tools (DataDog, CloudWatch, etc.) and the centralized logging system.

## Schema Version
`1.0.0`

## Required Fields

Every log entry MUST contain these fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `timestamp` | string | ISO 8601 timestamp (UTC) | `"2025-01-21T10:30:00.123Z"` |
| `level` | string | Log level (UPPERCASE) | `"INFO"`, `"ERROR"`, `"DEBUG"` |
| `logger` | string | Python logger name | `"scraper_backend.scrapers.executor"` |
| `message` | string | Human-readable message | `"Starting workflow execution"` |
| `job_id` | string \| null | Current scrape job ID | `"job_12345"` |
| `runner_name` | string | Configured runner identity | `"runner-prod-01"` |

## Optional Fields

Include these fields when relevant context exists:

| Field | Type | Description |
|-------|------|-------------|
| `scraper_name` | string | Name of scraper config being used |
| `sku` | string | Product SKU currently being processed |
| `step` | string | Current workflow step name |
| `action` | string | Action type (e.g., `navigate`, `extract`) |
| `duration_ms` | integer | Execution time in milliseconds |
| `error_type` | string | Exception class name |
| `error_message` | string | Detailed error description |
| `stack_trace` | string | Full stack trace (for errors only) |
| `context` | object | Additional structured data |

## Redaction Rules

**CRITICAL:** The logging system automatically redacts sensitive information before emission.

1. **Credentials**: Any value for keys matching `*password*`, `*secret*`, `*key*`, `*token*`
2. **API Keys**: Patterns matching `bsr_[a-zA-Z0-9]+`
3. **Cookies**: Contents of `Cookie` or `Set-Cookie` headers
4. **PII**: Email addresses, phone numbers (best effort)

Redacted values are replaced with `[REDACTED]`.

## Examples

### Info Log
```json
{
  "timestamp": "2025-01-21T10:30:05.123Z",
  "level": "INFO",
  "logger": "scraper_backend.scrapers.executor",
  "message": "Successfully navigated to product page",
  "job_id": "job_123",
  "runner_name": "worker-01",
  "scraper_name": "amazon_products",
  "sku": "B08X5H",
  "action": "navigate",
  "duration_ms": 1250
}
```

### Error Log
```json
{
  "timestamp": "2025-01-21T10:30:10.555Z",
  "level": "ERROR",
  "logger": "scraper_backend.core.retry",
  "message": "Element not found after retries",
  "job_id": "job_123",
  "runner_name": "worker-01",
  "scraper_name": "amazon_products",
  "sku": "B08X5H",
  "error_type": "TimeoutError",
  "error_message": "Timeout 30000ms exceeded while waiting for selector '.price'",
  "stack_trace": "Traceback (most recent call last)...\n..."
}
```

### Warning Log
```json
{
  "timestamp": "2025-01-21T10:30:08.777Z",
  "level": "WARNING",
  "logger": "scraper_backend.scrapers.extract",
  "message": "Optional field 'rating' not found",
  "job_id": "job_123",
  "runner_name": "worker-01",
  "scraper_name": "amazon_products",
  "sku": "B08X5H",
  "context": {
    "selector": ".star-rating"
  }
}
```

### Debug Log
```json
{
  "timestamp": "2025-01-21T10:30:01.000Z",
  "level": "DEBUG",
  "logger": "scraper_backend.utils.debugging",
  "message": "Selector validation result",
  "job_id": null,
  "runner_name": "local-dev",
  "context": {
    "selector": "div.price",
    "matches": 1,
    "first_match_text": "$19.99"
  }
}
```
