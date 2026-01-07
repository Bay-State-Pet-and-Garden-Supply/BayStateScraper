# BayStateScraper

Distributed headless scraper runners for Bay State Pet & Garden Supply product data collection.

This project contains the **headless runner** component of the Bay State scraping system. It is designed to run in Docker containers (GitHub Actions or self-hosted) and communicate with the BayStateApp coordinator via API.

## Project Structure

```
BayStateScraper/
├── core/               # Python core engine (API client, events)
├── scrapers/           # Scraper configs and executor logic
├── api/                # FastAPI debug server (optional)
├── utils/              # Debugging and utility tools
├── runner.py           # Main CLI entry point
├── Dockerfile          # Production Docker image
└── requirements.txt    # Python dependencies
```

## Quick Start

### 1. Production Runner (Self-Hosted)

Set up a new machine as a scraping runner in **under 5 minutes**:

```bash
# 1. Get your runner token from:
#    https://github.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/settings/actions/runners/new

# 2. Run the bootstrap script:
curl -fsSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/scripts/bootstrap-runner.sh | bash
```

The script will:
- Install Docker (if needed)
- Download and configure GitHub Actions runner
- Register with correct labels (`self-hosted,docker`)
- Pull the scraper Docker image
- Install as a system service (auto-starts on boot)

### 2. Manual Docker Run

To run a specific job manually using the Docker image:

```bash
docker pull ghcr.io/bay-state-pet-and-garden-supply/baystate-scraper:latest
docker run --rm \
  -e SCRAPER_API_URL="https://app.baystatepet.com" \
  -e SCRAPER_API_KEY="bsr_your_key_here" \
  ghcr.io/bay-state-pet-and-garden-supply/baystate-scraper:latest \
  python -m runner --job-id YOUR_JOB_ID
```

### 3. Local Development

Prerequisites: Python 3.10+

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Create .env file
cp .env.example .env  # (create one with API_URL and API_KEY)

# Run a job manually
python -m runner --job-id <JOB_ID>
```

## Configuration

Runners are configured via environment variables. Create a `.env` file for local development:

```env
RUNNER_NAME=my-local-runner
SCRAPER_API_URL=https://app.baystatepet.com
SCRAPER_API_KEY=bsr_your_api_key_here
```

## GitHub Secrets

When running in GitHub Actions, the following secrets must be configured in your repository settings:

| Secret | Required | Description | Where to Get |
|--------|----------|-------------|--------------|
| `SCRAPER_API_URL` | Yes | BayStateApp base URL | Your deployment URL |
| `SCRAPER_API_KEY` | Yes | Runner authentication | Admin Panel → Runners → Create |
| `SCRAPER_WEBHOOK_SECRET` | Yes | HMAC fallback signing | Generate with `openssl rand -hex 32` |
| `SCRAPER_CALLBACK_URL` | Yes | Callback endpoint | `{SCRAPER_API_URL}/api/admin/scraping/callback` |
| `SUPABASE_URL` | Yes | Supabase project URL | Supabase Dashboard → Settings → API |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key | Supabase Dashboard → Settings → API → service_role |
| `SETTINGS_ENCRYPTION_KEY` | Yes | Decrypt stored credentials | Same key used when encrypting settings |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design and data flow
- [API Reference](docs/API_PROPOSAL.md) - Runner ↔ Coordinator communication

## Authentication

Runners authenticate using **API Keys**:

1. **Admin creates runner** in BayStateApp → generates API key
2. **Runner stores key** in environment variable `SCRAPER_API_KEY`
3. **All requests include** `X-API-Key: bsr_xxxxx` header
4. **BayStateApp validates** key against database

## Security

- **Vault Pattern**: The runner does not store site passwords. Instead, it uses "vault keys" to fetch and decrypt credentials at runtime:
    1. GitHub Actions passes vault keys (Supabase URL/Key, Encryption Key) to the Docker container.
    2. Runner connects to Supabase and downloads encrypted settings.
    3. Runner decrypts the data using `SETTINGS_ENCRYPTION_KEY`.
    4. Site credentials (e.g., Phillips, Orgill) are only available in memory during execution.
- **No direct database access**: Runners communicate strictly through the API and restricted Supabase service calls.
- **API keys are hashed** in database (SHA256)
- **RLS policies** ensure runners can only update their own status
