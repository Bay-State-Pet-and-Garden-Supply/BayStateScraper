# BAYSTATE SCRAPER

**Context:** Distributed Python scraping engine. Muscle of the operation.

## OVERVIEW
Docker-first distributed scraper network. Executes YAML-defined workflows via Playwright. Stateless runners communicate with BayStateApp coordinator via API.

**Stack:** Python 3.10+, Playwright, Docker, GitHub Actions (self-hosted), Tauri (desktop).

## STRUCTURE
```
.
├── runner.py              # CLI entry for orchestrated jobs
├── main.py                # CLI entry for local/manual runs
├── scraper_backend/       # Core engine package
│   ├── runner.py          # Job lifecycle management
│   ├── core/              # API client, health, retry, memory
│   ├── scrapers/          # Configs, actions, executor
│   └── utils/             # Logging, encryption, testing
├── core/                   # Shared utilities (mirrors scraper_backend/core)
├── scrapers/               # Additional configs (mirrors scraper_backend/scrapers)
├── src-tauri/              # Desktop app (Rust)
├── ui/                     # Desktop frontend (Vite + Tailwind v3)
└── install.py              # Runner provisioning wizard
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| **New Scraper** | `scrapers/configs/*.yaml` | YAML DSL, not Python |
| **New Action** | `scraper_backend/scrapers/actions/handlers/` | Inherit `BaseAction`, use decorator |
| **API Client** | `scraper_backend/core/api_client.py` | Auth & callbacks |
| **Workflow Engine** | `scraper_backend/scrapers/executor/` | YAML interpretation |
| **Desktop App** | `src-tauri/` | Rust + Python sidecar |

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
1. Create `new_action.py` in `scrapers/actions/handlers/`
2. Inherit from `BaseAction`
3. Decorate: `@ActionRegistry.register("action_name")`
4. Implement `execute(self, params: dict)`
5. Auto-discovered via `auto_discover_actions()`

## CONVENTIONS
- **Auth**: `X-API-Key` header (bsr_* prefix). No direct DB access.
- **Async**: Playwright async API for all browser ops
- **Data**: Emit via API callbacks, never write to DB directly
- **Logging**: Use `utils/logger.py` structured logging
- **Secrets**: Environment variables only, never in YAML

## ANTI-PATTERNS
- **NO** database credentials in runners
- **NO** hardcoded site logic in Python (use YAML DSL)
- **NO** direct Supabase/PostgreSQL connections
- **NO** synchronous I/O in scraper loop
- **NO** bypassing `ActionRegistry` for custom steps
- **NO** credentials in YAML configs

## COMMANDS
```bash
# Local execution
python -m scraper_backend.runner --job-id test --scraper amazon

# Docker build
docker build -t baystate-scraper .

# Desktop app
cd ui && npm run tauri dev
```
