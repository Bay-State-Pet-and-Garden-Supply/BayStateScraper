# BayStateScraper Development Setup

## Overview

BayStateScraper is a distributed Python scraping engine that executes YAML-defined workflows via Playwright. Stateless runners communicate with the BayStateApp coordinator via API.

## Prerequisites

- **Python**: 3.10 or higher (3.13.3 recommended)
- **Playwright**: For browser automation
- **Git**: For version control

## Quick Start

### 1. Clone and Navigate

```bash
cd BayStateScraper
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers

```bash
playwright install chromium
```

### 5. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `SCRAPER_API_URL` | BayStateApp API URL | `https://bay-state-app.vercel.app` |
| `SCRAPER_API_KEY` | API key (bsr_* prefix) | `bsr_dKsosI...` |

### 6. Verify Setup

```bash
python test_setup.py
```

Expected output:
```
BayStateScraper - Development Setup Test
============================================================
[Python Version]
  OK: Python 3.13.3 (compatible)

[Dependencies]
  OK: httpx
  OK: playwright
  OK: pyyaml
  OK: pydantic
  OK: rich
  OK: structlog
  OK: supabase

[API Configuration]
  OK: SCRAPER_API_URL: https://bay-state-app.vercel.app
  OK: SCRAPER_API_KEY: bsr_dKsosI...

[Config Parsing]
  OK: Parsed config: test-scraper

[API Health Check]
  WARN: Connection failed: Health check failed: API returned status 307
     This is expected if the API is unreachable

============================================================
  PASS: Python Version
  PASS: Dependencies
  PASS: API Configuration
  PASS: Config Parsing
  PASS: API Health Check

5/5 tests passed
```

### 7. Run Tests

```bash
python -m pytest tests/ -v
```

Expected: **161 tests passing, 0 failing, 4 skipped**

## Project Structure

```
BayStateScraper/
├── runner.py              # CLI entry for orchestrated jobs
├── main.py                # CLI entry for local/manual runs
├── scraper_backend/       # Core engine package
│   ├── runner.py          # Job lifecycle management
│   ├── core/              # API client, health, retry, memory
│   ├── scrapers/          # Configs, actions, executor
│   └── utils/             # Logging, encryption, testing
├── core/                  # Shared utilities (mirrors scraper_backend/core)
├── scrapers/              # Additional configs (mirrors scraper_backend/scrapers)
├── tests/                 # Test suite
├── requirements.txt       # Dependencies
├── .env                   # Environment configuration
└── test_setup.py         # Development setup verification
```

## Key Components

### Configuration (YAML DSL)

Scrapers are defined in YAML files with the following structure:

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

### API Client (`scraper_backend/core/api_client.py`)

Handles all communication with BayStateApp:

- **Retry Logic**: Exponential backoff (1s, 2s, 4s delays)
- **Health Checks**: Fail-fast on connection failures
- **Error Handling**: Specific exception types (ConnectionError, ConfigurationError)

### Structured Logging (`scraper_backend/utils/structured_logging.py`)

JSON-formatted logs with job context:

```json
{
  "timestamp": "2026-02-05T21:33:43.658510Z",
  "level": "INFO",
  "logger": "scraper_backend.core.api_client",
  "message": "Making request to /api/v1/jobs/config",
  "job_id": "job-abc123",
  "scraper_name": "amazon"
}
```

## Common Commands

```bash
# Local execution with specific scraper
python -m scraper_backend.runner --job-id test --scraper amazon

# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_runner_config_errors.py -v

# Run with coverage
python -m pytest tests/ --cov=scraper_backend --cov-report=html

# Verify setup
python test_setup.py
```

## Development Workflow

### Adding New Actions

1. Create `new_action.py` in `scraper_backend/scrapers/actions/handlers/`
2. Inherit from `BaseAction`
3. Decorate: `@ActionRegistry.register("action_name")`
4. Implement `execute(self, params: dict)`
5. Auto-discovered via `auto_discover_actions()`

### Testing Changes

```bash
# 1. Verify setup
python test_setup.py

# 2. Run related tests
python -m pytest tests/test_runner_config_errors.py -v
python -m pytest tests/unit/test_api_client.py::TestRetryLogic -v
python -m pytest tests/unit/test_api_client.py::TestHealthCheck -v

# 3. Run full test suite
python -m pytest tests/ -v
```

### Error Handling Patterns

**Configuration Errors** (fail loudly):
```python
from scraper_backend.core.config_errors import ConfigurationError

try:
    config = parser.load_from_dict(raw_config)
except ValidationError as e:
    raise ConfigurationError(f"Invalid config: {e}") from e
```

**Retry Logic** (exponential backoff):
```python
from scraper_backend.core.api_client import ScraperAPIClient, ConnectionError

client = ScraperAPIClient()
# Automatically retries on 500, 503, 429, network errors
result = client.make_request("GET", "/endpoint")
```

## Troubleshooting

### Python Version Issues

BayStateScraper requires Python 3.10+. Check version:
```bash
python --version
```

### Playwright Not Installed

```bash
pip install playwright
playwright install chromium
```

### Import Errors

Ensure virtual environment is activated:
```bash
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

### API Connection Failures

Health check returning 307 redirect is expected when:
- API URL is unreachable
- Network is offline
- API key is invalid

The scraper will retry and fail gracefully.

### Config Parsing Failures

Ensure selectors are a list, not a dict:

```yaml
# ✅ Correct
selectors:
  - name: "product_title"
    selector: "h1.title"

# ❌ Incorrect
selectors:
  product_title:
    selector: "h1.title"
```

## Related Documentation

- [AGENTS.md](AGENTS.md) - Project architecture and conventions
- [scraper_backend/core/api_client.py](scraper_backend/core/api_client.py) - API client implementation
- [scrapers/models/config.py](scrapers/models/config.py) - Configuration schema
