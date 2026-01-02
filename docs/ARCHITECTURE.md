# Architecture

## Current State: API-Driven (Implemented)

The scraper system uses a fully decoupled, API-driven architecture with **API Key authentication**.

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Admin Panel (One-Time Setup)                     │
│  1. Admin creates runner → API key generated (bsr_xxxx)                 │
│  2. Key stored in GitHub Secrets as SCRAPER_API_KEY                     │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Runtime Authentication                           │
│                                                                          │
│  Runner sends:  X-API-Key: bsr_xxxxx                                    │
│  BayStateApp:   Hash key → lookup in runner_api_keys → validate         │
│                                                                          │
│  ✓ No token refresh needed                                              │
│  ✓ Instant revocation via admin panel                                   │
│  ✓ Simple runner configuration                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Components

#### 1. The Coordinator (BayStateApp)
- **Role**: Central brain and API gateway
- **Responsibilities**:
    - Stores scraper configurations in Supabase
    - Issues and validates API keys
    - Triggers GitHub Actions via `workflow_dispatch`
    - Receives scrape results and updates product data
    - Provides admin UI for runner management

#### 2. The Runner (BayStateScraper)
- **Role**: Stateless worker
- **Responsibilities**:
    - Authenticates with API key (single header)
    - Fetches job configuration from `/api/scraper/v1/job`
    - Executes scraping logic (Playwright/Python)
    - Posts results to `/api/admin/scraping/callback`
    - **No database access** - knows nothing about Supabase

### Data Flow

```
1. Job Creation
   ┌─────────────┐
   │ Admin Panel │ creates scrape_job record
   │             │ triggers workflow_dispatch
   └──────┬──────┘
          │
          ▼
2. Runner Startup
   ┌─────────────┐
   │   Runner    │ GET /api/scraper/v1/job?job_id=xxx
   │             │ Headers: X-API-Key: bsr_xxxxx
   │             │ Receives: SKUs, scraper configs
   └──────┬──────┘
          │
          ▼
3. Execution
   ┌─────────────┐
   │   Runner    │ Spawns Playwright workers
   │             │ Scrapes each SKU/site
   └──────┬──────┘
          │
          ▼
4. Reporting
   ┌─────────────┐
   │   Runner    │ POST /api/admin/scraping/callback
   │             │ Headers: X-API-Key: bsr_xxxxx
   │             │ Body: { job_id, status, results }
   └──────┬──────┘
          │
          ▼
5. Data Ingestion
   ┌─────────────┐
   │ BayStateApp │ Updates products_ingestion.sources
   │             │ Sets pipeline_status = 'scraped'
   └─────────────┘
```

### Security Model

| Layer | Protection |
|-------|------------|
| **Transport** | HTTPS only |
| **Authentication** | API key in `X-API-Key` header |
| **Key Storage** | SHA256 hashed in `runner_api_keys` table |
| **Authorization** | RLS policies on `scraper_runners` table |
| **Fallback** | HMAC signature for Docker crash reports |
| **Isolation** | Runners have zero database credentials |

### Database Tables

```sql
-- API keys (hashed)
runner_api_keys
├── runner_name  → links to scraper_runners
├── key_hash     → SHA256 of the actual key
├── key_prefix   → First 12 chars for identification
├── expires_at   → Optional expiration
├── revoked_at   → Soft delete for audit trail
└── last_used_at → Updated on each auth

-- Runner status
scraper_runners
├── name         → Primary key
├── status       → online/offline/busy
├── last_seen_at → Last heartbeat
└── current_job_id → Active job reference
```

## Benefits

- **Security**: No database credentials leave the secure BayStateApp environment
- **Simplicity**: Single API key per runner, no token refresh logic
- **Flexibility**: Schema changes don't break runners (API contract is stable)
- **Auditability**: All key usage tracked with timestamps
- **Scalability**: Multiple runners connect to same API endpoints
