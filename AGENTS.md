# BAYSTATE SCRAPER

**Generated:** 2026-02-12  
**Commit:** e98ed30  
**Branch:** dev  
**Context:** Distributed Python scraping engine. Muscle of the operation.

## OVERVIEW
Docker-first distributed scraper network. Executes YAML-defined workflows via async Playwright. Stateless runners communicate with BayStateApp coordinator via API.

**Stack:** Python 3.10+, Playwright (async), Docker, GitHub Actions (self-hosted), Tauri (desktop).

## STRUCTURE
```
.
├── daemon.py              # Docker ENTRYPOINT - polling daemon
├── runner.py              # CLI entry (5 lines, imports runner/)
├── runner/                # Unified runner package
│   ├── full_mode.py       # Full scrape execution
│   ├── chunk_mode.py      # Chunk worker mode
│   ├── realtime_mode.py   # Supabase Realtime listener
│   └── cli.py             # Argument parsing
├── core/                  # Infrastructure services
│   ├── api_client.py      # API communication
│   ├── events.py          # Event bus system
│   ├── retry_executor.py  # Retry logic
│   ├── realtime_manager.py # Supabase Realtime
│   └── ...
├── scrapers/              # Scraping domain
│   ├── actions/handlers/  # 21 action implementations
│   ├── executor/          # Workflow engine (decomposed)
│   ├── context.py         # ScraperContext Protocol
│   └── configs/*.yaml     # Scraper definitions
├── utils/                 # Utilities
│   ├── scraping/          # Browser wrappers
│   └── structured_logging.py
└── src-tauri/             # Desktop app (Rust)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| **New Scraper** | `scrapers/configs/*.yaml` | YAML DSL, not Python |
| **New Action** | `scrapers/actions/handlers/*.py` | Inherit `BaseAction`, register via decorator |
| **Action Registry** | `scrapers/actions/registry.py` | Auto-discovery via `@ActionRegistry.register()` |
| **Workflow Engine** | `scrapers/executor/` | Decomposed: browser_manager, selector_resolver, etc. |
| **API Client** | `core/api_client.py` | Auth & callbacks, no DB access |
| **Entry Points** | `daemon.py`, `runner.py` | Daemon for Docker, runner for CLI |

## KEY MODULES (Post-Refactor)

### Extracted Modules (from WorkflowExecutor god class)
- `scrapers/executor/browser_manager.py` — Browser lifecycle (async)
- `scrapers/executor/selector_resolver.py` — Element finding/extraction
- `scrapers/executor/debug_capture.py` — Debug artifacts
- `scrapers/executor/normalization.py` — Result normalization
- `scrapers/executor/step_executor.py` — Step execution with retry

### Protocol
- `scrapers/context.py` — `ScraperContext` Protocol for loose coupling

### Typed Results
- `scrapers/models/result.py` — `ScrapeResult` Pydantic model

## YAML DSL STRUCTURE
```yaml
name: "Scraper Name"
base_url: "https://..."
timeout: 30
retries: 3

selectors:
  - name: "product_name"
    selector: "h1.title"
    attribute: "text"
    required: true

workflows:
  - action: "navigate"
    params: { url: "{base_url}/p/{sku}" }
  - action: "wait_for"
    params: { selector: "h1.title" }
  - action: "extract"
    params: { fields: ["product_name", "price"] }
```

## ADDING NEW ACTIONS
1. Create `{action_name}.py` in `scrapers/actions/handlers/`
2. `from scrapers.actions.base import BaseAction`
3. `@ActionRegistry.register("{action_name}")`
4. `async def execute(self, params: dict[str, Any]) -> Any:`
5. Access context via `self.ctx` (browser, results, config)
6. Auto-discovered on startup

## CONVENTIONS
- **Auth**: `X-API-Key` header (bsr_* prefix). No direct DB access.
- **Async**: ALL browser operations use async Playwright
- **Context**: Actions receive `ScraperContext` (loose coupling)
- **Data**: Emit via API callbacks, never write to DB directly
- **Logging**: Structured logging with job context
- **Secrets**: Environment variables only, never in YAML

## ANTI-PATTERNS
- **NO** database credentials in runners
- **NO** hardcoded site logic in Python (use YAML DSL)
- **NO** direct Supabase/PostgreSQL connections
- **NO** synchronous I/O in scraper loop
- **NO** bypassing `ActionRegistry` for custom steps
- **NO** credentials in YAML configs
- **NO** Selenium (removed in refactor)
- **NO** `SyncPlaywright` in production (debug utils only)

## COMMANDS
```bash
# Run daemon (Docker mode)
python daemon.py

# Run single job (with API)
python runner.py --job-id <uuid>

# Run local test
python -m pytest tests/test_workflow_executor.py -v

# Docker build
docker build -t baystate-scraper .

# Desktop app
cd src-tauri && cargo tauri dev
```

## TESTING
- **Framework**: pytest
- **Command**: `python -m pytest --tb=short`
- **Status**: 179 passed, 12 skipped, 0 failed

## ARCHITECTURE NOTES
- **Refactor Date**: 2026-02-12
- **Lines Reduced**: 797→581 (27% reduction in WorkflowExecutor)
- **Async Migration**: 21/21 handlers converted
- **Selenium**: Fully removed (0 references)
- **Runner Consolidation**: Unified multi-mode runner

## RELATED
- Parent project: `../BayStateApp/` (Next.js coordinator)
- Shared: `../AGENTS.md` (monorepo overview)

