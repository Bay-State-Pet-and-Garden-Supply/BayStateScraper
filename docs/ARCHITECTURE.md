# Architecture

## Current State (Deprecated)
Currently, the scraper runner operates with a hybrid model:
1.  **Trigger**: GitHub Actions `workflow_dispatch`.
2.  **Config**: Loaded from local files or pulled directly from Supabase using a **Service Role Key**.
3.  **Data**: Pushed directly to Supabase tables (`products`, `scrapers`, etc.).

**Risks**:
- **Security**: The runner requires full database admin access (`SUPABASE_SERVICE_ROLE_KEY`), which is a critical vulnerability if the runner environment is compromised.
- **Coupling**: The runner schema is tightly coupled to the database schema.

## Target Architecture (API-Driven)

We are moving to a fully decoupled, API-driven architecture.

### 1. The Coordinator (BayStateApp)
- **Role**: The central brain.
- **Responsibilities**:
    - Stores scraper configurations.
    - Schedules jobs.
    - Exposes an API for runners to fetch work and submit results.
    - Manages authentication (issues runner tokens).

### 2. The Runner (This Project)
- **Role**: The dumb worker.
- **Responsibilities**:
    - Polls the API for jobs (or accepts webhooks).
    - Executes the scraping logic (Playwright/Python).
    - Returns standardized JSON results to the API.
    - **No Database Access**: It knows nothing about Supabase or SQL.

### Data Flow

1.  **Job Request**:
    - Coordinator -> Runner (API call or Webhook)
    - Payload: `{ "job_id": "123", "scrapers": ["amazon", "chewy"], "config": { ... } }`

2.  **Execution**:
    - Runner spawns workers.
    - Scrapers run using the provided config.

3.  **Reporting**:
    - Runner -> Coordinator (POST /api/v1/scraper/results)
    - Payload: `{ "job_id": "123", "sku": "ABC", "data": { ... }, "status": "success" }`

4.  **Logging**:
    - Runner -> Coordinator (POST /api/v1/scraper/logs)
    - Real-time stream of logs/events.

## Benefits
- **Security**: DB credentials never leave the secure Coordinator environment.
- **Flexibility**: The Coordinator can change DB schemas without breaking the Runner (as long as the API contract stays the same).
- **Scalability**: Multiple runners can connect to the same Coordinator API.
