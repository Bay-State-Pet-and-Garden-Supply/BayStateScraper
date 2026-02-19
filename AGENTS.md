# BAYSTATE SCRAPER

**Generated:** 2026-02-19  
**Commit:** 3bc979a  
**Branch:** main  
**Context:** Distributed Python scraping engine. Muscle of the operation.

## OVERVIEW
Docker-first distributed scraper network. Executes YAML-defined workflows via async Playwright. Stateless runners communicate with BayStateApp coordinator via API.

**Stack:** Python 3.10+, Playwright (async), Docker, GitHub Actions (self-hosted), Tauri (desktop).

## STRUCTURE
```
.
├── daemon.py              # Docker ENTRYPOINT - polling daemon
├── runner.py              # CLI entry (thin wrapper)
├── runner/                # Execution modes (full/chunk/realtime)
├── core/                  # Infrastructure services
│   ├── api_client.py      # API communication
│   ├── events.py          # Event bus system
│   ├── retry_executor.py  # Retry logic
│   ├── realtime_manager.py # Supabase Realtime
│   └── ...
├── scrapers/              # Scraping domain
│   ├── actions/handlers/  # 27 action implementations (all async)
│   ├── executor/          # Workflow engine (decomposed)
│   ├── events/            # Event system with WebSocket
│   ├── context.py         # ScraperContext Protocol
│   └── configs/*.yaml     # 12 scraper definitions
├── utils/                 # Utilities
└── src-tauri/             # Desktop app (Rust)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| **New Scraper** | `scrapers/configs/*.yaml` | YAML DSL, not Python |
| **New Action** | `scrapers/actions/handlers/*.py` | Inherit `BaseAction`, register via decorator |
| **Action Registry** | `scrapers/actions/registry.py` | Auto-discovery via `@ActionRegistry.register()` |
| **Workflow Engine** | `scrapers/executor/` | Decomposed: browser_manager, selector_resolver, etc. |
| **Event System** | `scrapers/events/` | EventEmitter, handlers, WebSocket |
| **API Client** | `core/api_client.py` | Auth & callbacks, no DB access |
| **Entry Points** | `daemon.py`, `runner.py` | Daemon for Docker, runner for CLI |
| **Execution Modes** | `runner/` | full_mode, chunk_mode, realtime_mode |

## KEY MODULES

### Actions (27 handlers)
All async actions in `scrapers/actions/handlers/`:
- **Navigation:** navigate, click, wait, wait_for, wait_for_hidden
- **Extraction:** extract, extract_and_transform, transform_value, table, json
- **AI:** ai_search, ai_extract, ai_validate, ai_base
- **Input:** input, login, verify
- **Flow:** conditional, conditional_skip, combine, script
- **Utilities:** browser, image, sponsored, weight, anti_detection

### Executor (Decomposed)
- `workflow_executor.py` — Main orchestrator
- `browser_manager.py` — Browser lifecycle (async)
- `selector_resolver.py` — Element finding/extraction
- `step_executor.py` — Step execution with retry
- `debug_capture.py` — Debug artifacts
- `normalization.py` — Result normalization

### Context Protocol
- `scrapers/context.py` — `ScraperContext` Protocol for loose coupling

### Models
- `scrapers/models/config.py` — `ScraperConfig` Pydantic model
- `scrapers/models/result.py` — `ScrapeResult` Pydantic model

## YAML DSL STRUCTURE
```yaml
name: "Scraper Name"
base_url: "https://..."
timeout: 30
retries: 3
image_quality: 85

selectors:
  - name: "product_name"
    selector: "h1.title"
    attribute: "text"
    required: true
    transform: [{type: "strip"}]

workflows:
  - action: "navigate"
    params: { url: "{base_url}/p/{sku}" }
  - action: "wait_for"
    params: { selector: "h1.title" }
  - action: "extract"
    params: { fields: ["product_name", "price"] }

# Optional sections
anti_detection:
  enabled: true
  human_simulation: true

validation:
  no_results_selector: ".no-results"
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
- **AI Actions**: Use `ai_base.py` for common AI patterns

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
- **Status**: Check with `python -m pytest --collect-only`

## ARCHITECTURE NOTES
- **Latest Commit**: 3bc979a feat(infra): implement AI fallback chain logic
- **Async**: All 27 handlers are async
- **Selenium**: Fully removed (0 references)
- **Configs**: 12 YAML scraper definitions

## RELATED
- Parent project: `../BayStateApp/` (Next.js coordinator)
- Shared: `../AGENTS.md` (monorepo overview)

