# BayStateScraper Agent Guide

## OVERVIEW
- Python 3.10 based distributed scraping engine.
- Docker-first deployment on self-hosted runners.
- Orchestrated by BayStateApp via workflow dispatch.
- YAML DSL for defining scraper logic without code changes.

## STRUCTURE
```
.
├── BayStateScraper/
│   ├── scraper_backend/    # Main package
│   │   ├── runner.py       # Entry point for job execution
│   │   ├── scrapers/
│   │   │   ├── configs/    # YAML scraper definitions (DSL)
│   │   │   ├── actions/    # Reusable action handlers & registry
│   │   │   └── executor/   # DSL interpretation & flow control
│   │   └── core/           # API client, retries, and health monitors
│   └── install.py          # Runner provisioning script
```

## WHERE TO LOOK
| Component | Path | Purpose |
|-----------|------|---------|
| Entry Point | `scraper_backend/runner.py` | CLI for starting jobs |
| DSL Configs | `scrapers/configs/*.yaml` | Scraper logic definitions |
| Action Logic | `scrapers/actions/handlers/` | Python implementation of YAML actions |
| Action Map | `scrapers/actions/registry.py` | Mapping YAML keys to Python classes |
| API Client | `core/api_client.py` | Auth and callback logic |

## CONVENTIONS
- **Auth**: Use `X-API-Key` (starts with `bsr_`). No direct DB access.
- **Scraper Dev**: Add/edit YAML in `configs/`. Avoid Python code for site logic.
- **Actions**: Register new action types in `registry.py`.
- **Async**: Use Playwright async API for browser interactions.
- **Data**: Scrapers emit raw/mapped data via API callbacks.

## ANTI-PATTERNS
- **NO** database credentials in runner environment or code.
- **NO** hardcoded site-specific logic in Python files (use YAML DSL).
- **NO** direct Supabase/PostgreSQL connections (use `api_client`).
- **NO** synchronous I/O in scraper loop (use `asyncio`).
- **NO** manual result handling (use `result_collector`).
