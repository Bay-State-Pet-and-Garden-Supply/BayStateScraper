# API Proposal: Runner Communication

To replace the direct Supabase connection, we will implement the following API contract between the Runner and the Main Application.

## 1. Configuration Fetching
Instead of `supabase.table("scrapers").select("*")`:

**GET /api/runner/config**
- **Headers**: `Authorization: Bearer <RUNNER_TOKEN>`
- **Response**:
  ```json
  {
    "scrapers": [
      {
        "name": "amazon",
        "enabled": true,
        "base_url": "...",
        "selectors": { ... }
      }
    ],
    "global_settings": {
      "timeout": 30000
    }
  }
  ```

## 2. Job Reporting
Instead of `supabase.table("products").upsert(...)`:

**POST /api/runner/results**
- **Headers**: `Authorization: Bearer <RUNNER_TOKEN>`
- **Body**:
  ```json
  {
    "job_id": "job_123",
    "sku": "SKU-001",
    "scraper": "amazon",
    "status": "success",
    "data": {
      "price": 10.99,
      "stock": "In Stock",
      "url": "..."
    },
    "metadata": {
      "duration_ms": 1500,
      "retries": 1
    }
  }
  ```

## 3. Logs & Health
Instead of `supabase.table("scraper_health").update(...)`:

**POST /api/runner/telemetry**
- **Headers**: `Authorization: Bearer <RUNNER_TOKEN>`
- **Body**:
  ```json
  {
    "runner_id": "runner-01",
    "status": "healthy",
    "cpu_usage": 45,
    "memory_usage": 1024,
    "active_jobs": 2
  }
  ```

## Transition Plan
1.  **Phase 1**: Implement these endpoints in the Main Application.
2.  **Phase 2**: Update `scraper_backend` to prefer API calls over `supabase_sync.py` if an API URL is configured.
3.  **Phase 3**: Remove `supabase_sync.py` and Supabase dependencies from the runner entirely.
