# BayStateScraper - Agent Development Guidelines

## Overview

Distributed scraper runners for Bay State Pet & Garden Supply. Deployed to Docker containers on self-hosted GitHub Actions runners. Communicates with BayStateApp via **API Key authentication**.

## Commands

```bash
# Build Docker image
docker build -t baystate-scraper:latest scraper_backend/

# Run locally
python -m scraper_backend.runner --job-id <JOB_ID>

# Manual workflow trigger
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=amazon,chewy \
  -f test_mode=true

# Setup a new runner
python install.py
```

## Code Style

- **Python:** 3.10+, 100 char line length
- **Linting:** ruff (E, F, B, I, N, UP, PL, RUF)
- **Typing:** Type hints required
- **Naming:** snake_case (functions/vars), PascalCase (classes)
- **Async:** async/await for I/O operations

## Architecture

```
BayStateApp (Admin)
    │
    │ Creates scrape_job, triggers workflow_dispatch
    ▼
GitHub Actions (self-hosted runner)
    │
    │ Runs Docker container
    ▼
Runner (this project)
    │
    │ Auth: X-API-Key header
    │ GET /api/scraper/v1/job → fetch config
    │ Executes scraping
    │ POST /api/admin/scraping/callback → submit results
    ▼
BayStateApp (API)
    │
    │ Validates key, updates database
    ▼
Supabase (products_ingestion table)
```

## Key Directories

```
scraper_backend/
├── core/
│   ├── api_client.py    # HTTP client with API key auth
│   └── database/        # Legacy Supabase sync (deprecated)
├── scrapers/
│   ├── configs/         # YAML scraper definitions
│   ├── actions/         # Scraper action handlers
│   └── executor/        # Workflow execution engine
├── runner.py            # Job runner entry point
└── run_job.py           # Alternative entry point
cli/
└── runner_setup.py      # Standalone setup CLI
docs/
├── ARCHITECTURE.md      # System design
└── API_PROPOSAL.md      # API reference
```

## Authentication

Runners use **API Keys** (not passwords):

```python
# Environment variable
SCRAPER_API_KEY=bsr_xxxxx

# Sent as header on all requests
X-API-Key: bsr_xxxxx
```

Get keys from: Admin Panel → Scraper Network → Runner Accounts

## Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `SCRAPER_API_URL` | BayStateApp base URL |
| `SCRAPER_API_KEY` | API key (starts with `bsr_`) |
| `SCRAPER_WEBHOOK_SECRET` | HMAC secret for crash fallback |
| `SCRAPER_CALLBACK_URL` | Callback URL for HMAC fallback |

## Rules

- Scrapers defined in YAML, not hardcoded
- **No database credentials** on runners
- All auth via API key header
- Respect robots.txt, use proper user-agents
- Data processing happens in BayStateApp after callback
