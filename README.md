# BayStateScraper

Distributed scraper runners for Bay State Pet & Garden Supply product data collection.

## Quick Start

### One-Line Install

Run this on any Mac or Linux machine:

```bash
curl -fsSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/install.py | python3
```

The installer will:
1. Install Python dependencies
2. Prompt you to paste your **API Key** (from BayStateApp admin panel)
3. Register the runner with BayStateApp
4. Save configuration locally

### Get Your API Key First

1. Go to **BayStateApp Admin Panel** → **Scraper Network** → **Runner Accounts**
2. Click **"Create Runner"** and enter a name for this machine
3. **Copy the API key** (starts with `bsr_`) - it's only shown once!
4. Run the installer above and paste the key when prompted

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design and data flow
- [API Reference](docs/API_PROPOSAL.md) - Runner ↔ Coordinator communication

## Manual Setup

If you prefer manual setup or already have the repo cloned:

```bash
python install.py
```

### Prerequisites

- Python 3.9+
- Docker (optional, for containerized deployment)

### Install Dependencies

```bash
pip install -r scraper_backend/requirements.txt
python -m playwright install chromium
```

### Configure Environment

Create `scraper_backend/.env`:

```env
# Runner Identity
RUNNER_NAME=my-runner

# API Configuration
SCRAPER_API_URL=https://app.baystatepet.com

# API Key Authentication (get from Admin Panel)
SCRAPER_API_KEY=bsr_your_api_key_here
```

## Docker Deployment

### Build the Docker image

```bash
cd scraper_backend
docker build -t baystate-scraper:latest .
```

### GitHub Actions Secrets

Configure these in your repository settings:

| Secret | Description |
|--------|-------------|
| `SCRAPER_API_URL` | Base URL to BayStateApp (e.g., `https://app.baystatepet.com`) |
| `SCRAPER_API_KEY` | API key from admin panel (starts with `bsr_`) |
| `SCRAPER_WEBHOOK_SECRET` | Shared secret for HMAC fallback (Docker crash reporting) |
| `SCRAPER_CALLBACK_URL` | Callback URL for HMAC fallback |

## Usage

The scraper is triggered via `workflow_dispatch` from the BayStateApp admin panel.

### Manual trigger (for testing)

```bash
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=amazon,chewy \
  -f test_mode=true
```

### Local testing

```bash
python -m scraper_backend.runner --job-id test-123
```

## Architecture

```
                    ┌─────────────────┐
                    │   BayStateApp   │
                    │  (Admin Panel)  │
                    └────────┬────────┘
                             │ workflow_dispatch
                             ▼
                    ┌─────────────────┐
                    │  GitHub Actions │
                    │  (This Repo)    │
                    └────────┬────────┘
                             │ runs-on: self-hosted
                             ▼
                    ┌─────────────────┐
                    │  Docker Runner  │
                    │ baystate-scraper│
                    │                 │
                    │ Auth: X-API-Key │
                    └────────┬────────┘
                             │ POST /api/admin/scraping/callback
                             ▼
                    ┌─────────────────┐
                    │   BayStateApp   │
                    │  (API Callback) │
                    └─────────────────┘
```

## Authentication

Runners authenticate using **API Keys** (not passwords):

1. **Admin creates runner** in BayStateApp → generates API key
2. **Runner stores key** in environment variable `SCRAPER_API_KEY`
3. **All requests include** `X-API-Key: bsr_xxxxx` header
4. **BayStateApp validates** key against database, processes request

Benefits over password-based auth:
- No token refresh needed
- Easy key rotation via admin panel
- Instant revocation
- Simpler runner configuration

## Security

- **No database credentials** on runners - all communication via API
- **API keys are hashed** in database (SHA256)
- **HMAC fallback** for Docker crash reporting
- **RLS policies** ensure runners can only update their own status
