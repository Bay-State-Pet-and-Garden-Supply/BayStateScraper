# API Reference: Runner ↔ Coordinator Communication

This document describes the API contract between scraper runners and the BayStateApp coordinator.

## Authentication

All endpoints require an API key in the `X-API-Key` header:

```http
X-API-Key: bsr_your_api_key_here
```

API keys are issued from the BayStateApp admin panel and start with `bsr_`.

### Fallback: HMAC Signature

For Docker crash scenarios (where the Python client isn't available), the GitHub Action can send an HMAC-signed request:

```http
X-Webhook-Signature: <sha256-hmac-of-body>
```

## Endpoints

### 1. Get Job Configuration

Fetch job details and scraper configurations.

**GET /api/scraper/v1/job**

Query Parameters:
- `job_id` (required): UUID of the scrape job

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "skus": ["SKU-001", "SKU-002"],
  "scrapers": [
    {
      "name": "amazon",
      "disabled": false,
      "base_url": "https://amazon.com",
      "search_url_template": "/s?k={sku}",
      "selectors": { ... },
      "options": { ... }
    }
  ],
  "test_mode": false,
  "max_workers": 3
}
```

### 2. Submit Results

Report job status and scraped data.

**POST /api/admin/scraping/callback**

Request Body:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "runner_name": "office-mac",
  "results": {
    "skus_processed": 25,
    "scrapers_run": ["amazon", "chewy"],
    "data": {
      "SKU-001": {
        "amazon": {
          "price": 29.99,
          "title": "Premium Dog Food",
          "url": "https://amazon.com/dp/...",
          "scraped_at": "2024-01-15T10:30:00Z"
        }
      }
    }
  }
}
```

Status values:
- `running` - Job started
- `completed` - Job finished successfully
- `failed` - Job failed (include `error_message`)

### 3. Register Runner

Register a new runner or update existing.

**POST /api/admin/scraper-network/runners/register**

Request Body:
```json
{
  "runner_name": "garage-pi",
  "metadata": {
    "platform": "Linux",
    "python_version": "3.11",
    "hostname": "raspberrypi"
  }
}
```

Response:
```json
{
  "success": true,
  "runner": {
    "name": "garage-pi",
    "status": "online",
    "registered_at": "2024-01-15T10:30:00Z"
  },
  "message": "Runner 'garage-pi' registered successfully"
}
```

### 4. Health Check

Verify API connectivity.

**GET /api/admin/scraper-network/health**

Response:
```json
{
  "checks": [
    { "name": "GitHub App", "status": "ok", "message": "Configured" },
    { "name": "Runner Auth", "status": "ok", "message": "API Key authentication" },
    { "name": "Webhook Secret", "status": "ok", "message": "HMAC fallback configured" }
  ]
}
```

## Error Responses

All errors follow this format:

```json
{
  "error": "Description of what went wrong"
}
```

Common HTTP status codes:
- `400` - Bad request (missing/invalid parameters)
- `401` - Unauthorized (invalid or missing API key)
- `404` - Not found (job doesn't exist)
- `500` - Server error

## Python Client Example

```python
from scraper_backend.core.api_client import ScraperAPIClient

client = ScraperAPIClient(
    api_url="https://app.baystatepet.com",
    api_key="bsr_your_key_here",
    runner_name="my-runner"
)

# Fetch job config
config = client.get_job_config("job-uuid")

# Submit results
client.submit_results(
    job_id="job-uuid",
    status="completed",
    results={"skus_processed": 10, "data": {...}}
)
```
