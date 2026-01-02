# BayState Scraper

Self-hosted scraper for Bay State Pet & Garden Supply product data collection.

## Quick Start (One-Line Install)

Run this on any Mac or Linux machine:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/BayStateScraper/main/install.sh | bash
```

The installer will:
1. Install Python if needed
2. Download the runner setup tool
3. Walk you through configuration
4. Register the runner with BayStateApp

No git or manual cloning required.

### After Installation

```bash
# Check status
~/.baystate-runner/baystate-runner status

# Re-login
~/.baystate-runner/baystate-runner login
```

## Documentation
- [Project Goals](docs/GOALS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API Proposal](docs/API_PROPOSAL.md)

## Overview

This repository contains the Python-based scraper that runs on self-hosted GitHub Actions runners. It collects product data from various supplier websites and reports results back to the main BayStateApp via secure webhooks.

## Alternative: Manual Setup

If you prefer manual setup or already have the repo cloned:

```bash
python install.py
```

### Prerequisites
- Python 3.9+
- Docker (optional, for containerized deployment)
- GitHub Actions self-hosted runner (for production)

### Install Dependencies

```bash
pip install -r scraper_backend/requirements.txt
python -m playwright install chromium
```

### Configure Environment

Create `scraper_backend/.env`:

```env
RUNNER_NAME=my-runner
SCRAPER_API_URL=http://localhost:3000
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=your-anon-key
RUNNER_EMAIL=runner@scraper.local
RUNNER_PASSWORD=from-admin-panel
```

### Get Runner Credentials

1. Go to BayStateApp admin panel -> Scraper Network -> Runner Accounts
2. Click "Create Account" and enter a runner name
3. Copy the generated email and password
4. Update your `.env` file

## Docker Deployment

### Build the Docker image

```bash
cd scraper_backend
docker build -t baystate-scraper:latest .
```

### GitHub Actions Secrets

Configure these in repository settings:

| Secret | Description |
|--------|-------------|
| `SCRAPER_API_URL` | Base URL to BayStateApp |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon key |
| `RUNNER_EMAIL` | Runner account email |
| `RUNNER_PASSWORD` | Runner account password |

## Usage

The scraper is triggered via `workflow_dispatch` from the BayStateApp admin panel.

### Manual trigger (for testing)

```bash
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=supplier1,supplier2 \
  -f test_mode=true
```

### Local testing

```bash
./run_local_job.sh --job-id test-123
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
                    └────────┬────────┘
                             │ webhook callback
                             ▼
                    ┌─────────────────┐
                    │   BayStateApp   │
                    │  (API Callback) │
                    └─────────────────┘
```
