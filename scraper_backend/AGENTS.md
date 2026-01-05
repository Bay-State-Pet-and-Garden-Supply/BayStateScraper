# BAYSTATE SCRAPER BACKEND

**Focus:** Distributed Scraper Engine & YAML-based Workflow DSL.

## OVERVIEW
High-performance scraper engine using Playwright.
Executes multi-step workflows defined in YAML configs.
Decouples site-specific logic (YAML) from engine core (Python).

## ENGINE ARCHITECTURE
- **models/config.py**: Pydantic models (`ScraperConfig`). Defines DSL schema.
- **parser/yaml_parser.py**: Loads/validates YAML into Pydantic objects.
- **executor/workflow_executor.py**: Orchestrator. Manages browser, context, retries.
- **actions/registry.py**: Command registry with auto-discovery of handlers.
- **actions/handlers/**: Atomic action implementations (click, navigate, extract).

## WORKFLOW EXECUTION FLOW
1. `Runner` loads YAML via `ScraperConfigParser`.
2. `WorkflowExecutor` initializes Playwright browser session.
3. Steps iterated; `ActionRegistry` fetches handler for `step.action`.
4. Handler executes using `executor.browser` and `step.params`.
5. `RetryExecutor` wraps steps for adaptive recovery (CAPTCHA, blocks).

## EXTENDING: ADDING NEW ACTIONS
1. Create `new_action.py` in `actions/handlers/`.
2. Inherit from `BaseAction`.
3. Decorate with `@ActionRegistry.register("action_name")`.
4. Implement `execute(self, params: dict)`.
5. Action auto-registers via `auto_discover_actions()`.

## CORE MODELS (Pydantic)
- `ScraperConfig`: Root configuration (base_url, retries, anti_detection).
- `WorkflowStep`: Action name + flexible parameter mapping.
- `SelectorConfig`: CSS/XPath logic for data extraction.

## ANTI-PATTERNS
- **NO** hardcoded site logic in `WorkflowExecutor`. Use Actions.
- **NO** manual Playwright calls in YAML configs. Use DSL.
- **NO** credentials in YAML. Use env vars/secrets.
- **NO** mixed backends. Playwright is the only supported driver.
- **NO** bypassing `ActionRegistry` for custom step logic.

## COMMANDS
```bash
# Local test run
python -m scraper_backend.runner --job-id test --scraper amazon
```
