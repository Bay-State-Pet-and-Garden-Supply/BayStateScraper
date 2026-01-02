# BayStateScraper - Agent Development Guidelines

## Overview
Self-hosted scraper runners for Bay State Pet & Garden Supply product data collection. Deployed to Docker containers on self-hosted GitHub Actions runners.

## Commands

```bash
# Build
docker build -t baystate-scraper:latest scraper_backend/

# Manual workflow trigger (testing)
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=supplier1,supplier2 \
  -f test_mode=true
```

## Code Style

- **Python:** 3.10+, 100 char line length
- **Linting:** ruff (E, F, B, I, N, UP, PL, RUF)
- **Typing:** Type hints required
- **Naming:** snake_case (functions/vars), PascalCase (classes)
- **Async:** async/await for I/O operations

## Architecture

```
BayStateApp (Admin) → workflow_dispatch → GitHub Actions → Self-hosted Runner → Docker → Webhook → BayStateApp
```

## Key Directories

```
scraper_backend/
├── scrapers/
│   ├── configs/     # YAML scraper definitions
│   └── actions/     # Scraper action implementations
├── core/            # Core scraping engine
└── utils/           # Utilities, logging
docs/
├── GOALS.md         # Project goals
├── ARCHITECTURE.md  # Technical architecture
└── API_PROPOSAL.md  # API design
```

## Required Secrets (GitHub)

| Secret | Description |
|--------|-------------|
| `SCRAPER_CALLBACK_URL` | BayStateApp callback endpoint |
| `SCRAPER_WEBHOOK_SECRET` | HMAC signature verification |

## Integration with BayStateApp

- Triggered via `workflow_dispatch` from admin panel
- Reports results via secure webhook POST
- Status tracked in `scraper_runs` table

## Rules

- Scrapers defined in YAML, not hardcoded
- Respect robots.txt, use proper user-agents
- All scraping logic stays in this repo
- Data processing happens in BayStateApp after webhook
