# SCRAPER BACKEND ENGINE

**Context:** Core YAML DSL interpreter and workflow executor.

## OVERVIEW
High-performance scraping engine. Translates YAML configs into Playwright browser automation. Decouples site logic (YAML) from engine core (Python).

## STRUCTURE
```
.
├── runner.py                  # Job lifecycle, event emission
├── run_job.py                 # Docker entry point
├── core/
│   ├── api_client.py          # Auth, job fetch, result callbacks
│   ├── scraper_health_monitor.py  # Real-time diagnostics (1000+ lines)
│   ├── memory_manager.py      # Container resource management
│   ├── retry_executor.py      # Adaptive retry with backoff
│   └── failure_classifier.py  # CAPTCHA, rate limit detection
├── scrapers/
│   ├── configs/               # YAML scraper definitions
│   ├── models/config.py       # Pydantic DSL schema
│   ├── parser/yaml_parser.py  # YAML → Pydantic validation
│   ├── executor/workflow_executor.py  # Core orchestrator (900+ lines)
│   └── actions/
│       ├── registry.py        # Action name → class mapping
│       └── handlers/          # navigate, click, extract, etc.
└── utils/
    ├── logger.py              # Structured logging
    └── encryption.py          # API key handling
```

## EXECUTION FLOW
1. `Runner` loads YAML via `ScraperConfigParser`
2. `WorkflowExecutor` initializes Playwright browser
3. Steps iterated; `ActionRegistry` fetches handler for each `action`
4. Handler executes using `executor.browser` and `step.params`
5. `RetryExecutor` wraps steps for adaptive recovery
6. Results collected and POSTed via `api_client`

## KEY MODELS (Pydantic)
- `ScraperConfig`: Root (base_url, retries, anti_detection)
- `WorkflowStep`: Action name + params
- `SelectorConfig`: CSS/XPath extraction rules

## AVAILABLE ACTIONS
| Action | Purpose | Key Params |
|--------|---------|------------|
| `navigate` | Change URL | `url` |
| `wait_for` | Wait for element | `selector`, `timeout` |
| `extract` | Bulk field extraction | `fields` |
| `click` | Click element | `selector` |
| `input_text` | Type into field | `selector`, `text` |
| `login` | Auth flow | `url`, `username_field`, `password_field` |
| `scroll` | Page scrolling | `direction`, `count` |

## ANTI-PATTERNS
- **NO** hardcoded site logic in `WorkflowExecutor`
- **NO** manual Playwright calls in YAML configs
- **NO** credentials in YAML (use env vars)
- **NO** bypassing `ActionRegistry`
- **NO** synchronous I/O in async context
