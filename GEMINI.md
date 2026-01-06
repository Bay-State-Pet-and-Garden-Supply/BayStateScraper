# BayStateScraper Context for Gemini

## Project Overview
**BayStateScraper** is a distributed scraper system for Bay State Pet & Garden Supply. It runs on self-hosted GitHub Actions runners in Docker containers, collecting product data from supplier websites.

**Key Technologies:**
- **Language:** Python 3.10+
- **Scraping:** Playwright
- **Container:** Docker
- **Orchestration:** GitHub Actions (workflow_dispatch)

## Building and Running

```bash
# Build Docker image
docker build -t baystate-scraper:latest scraper_backend/

# Manual workflow trigger
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=supplier1,supplier2 \
  -f test_mode=true
```

## Development Conventions

### Python
- **Style:** ruff configuration (line length 100)
- **Typing:** Type hints required
- **Naming:** snake_case for functions/variables, PascalCase for classes

### Workflow
- Scrapers defined in YAML (`scraper_backend/scrapers/configs/`)
- Triggered by BayStateApp admin panel
- Results posted back via secure webhook

## Key Documentation Files
- `docs/GOALS.md`: Project objectives
- `docs/ARCHITECTURE.md`: Technical architecture
- `docs/API_PROPOSAL.md`: API design

## Integration
- Receives `workflow_dispatch` from BayStateApp
- Posts scraping results to BayStateApp webhook endpoint
- Status tracked in BayStateApp's `scraper_runs` table
