# BayState Scraper

Self-hosted scraper for Bay State Pet & Garden Supply product data collection.

## Documentation
- [Project Goals](docs/GOALS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API Proposal](docs/API_PROPOSAL.md)

## Overview

This repository contains the Python-based scraper that runs on self-hosted GitHub Actions runners. It collects product data from various supplier websites and reports results back to the main BayStateApp via secure webhooks.

## Setup

### Prerequisites
- Docker installed on the runner machine
- GitHub Actions self-hosted runner configured with labels: `self-hosted`, `docker`

### Build the Docker image

```bash
cd scraper_backend
docker build -t baystate-scraper:latest .
```

### Required Secrets

Configure these in GitHub repository settings:

| Secret | Description |
|--------|-------------|
| `SCRAPER_API_URL` | Base URL to the BayStateApp (e.g., https://app.example.com) |
| `SUPABASE_URL` | Supabase project URL for authentication |
| `SUPABASE_ANON_KEY` | Supabase anon key for authentication |
| `RUNNER_EMAIL` | Runner account email (from admin panel) |
| `RUNNER_PASSWORD` | Runner account password (from admin panel) |

### Creating Runner Credentials

1. Go to the BayStateApp admin panel → Scraper Network → Runner Accounts
2. Click "Create Account" and enter a runner name
3. Copy the generated email and password
4. Configure these as `RUNNER_EMAIL` and `RUNNER_PASSWORD` secrets

## Usage

The scraper is triggered via `workflow_dispatch` from the main BayStateApp admin panel.

### Manual trigger (for testing)

```bash
gh workflow run scrape.yml \
  -f job_id=test-123 \
  -f scrapers=supplier1,supplier2 \
  -f test_mode=true
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
