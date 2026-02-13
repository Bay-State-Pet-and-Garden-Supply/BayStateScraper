# BayStateScraper v0.2.0

Distributed headless scraper runners for Bay State Pet & Garden Supply.

## What's New in v0.2.0

- **Supabase Realtime v2** - Real-time job dispatch and presence tracking
- **Structured JSON Logging** - Centralized logging with job context
- **Simplified Architecture** - Polling daemon mode for reliability
- **Test Lab Events** - Real-time event system for testing
- **Enhanced Installation** - Guided setup with realtime key configuration

## Quick Install

**One-liner** - paste this into your terminal:

```bash
curl -sSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/get.sh | bash
```

You'll be prompted for:
1. **API URL** - Your BayStateApp URL (default: `https://app.baystatepet.com`)
2. **API Key** - Get from Admin Panel → Scraper Network → Runner Accounts

That's it! The runner starts automatically and runs in the background.

## Development vs Production

The runner supports two environments:

| Environment | API URL | Use Case |
|-------------|---------|----------|
| **Development** | `http://localhost:3000` | Active development, testing new scrapers |
| **Production** | `https://bay-state-app.vercel.app` | Live data collection |

### Quick Start

```bash
# Development mode (connects to local app)
./run-dev.sh

# Production mode (connects to Vercel)
./run-prod.sh

# Or use Python directly
python daemon.py --env dev    # Development
python daemon.py --env prod   # Production (default)
```

### Environment Files

- `.env` - Production configuration (used by Docker)
- `.env.development` - Local development configuration

The runner automatically loads the correct file based on the `--env` flag.

## Commands

```bash
# View logs
docker logs -f baystate-scraper

# Stop runner
docker stop baystate-scraper

# Start runner
docker start baystate-scraper

# Update to latest version
curl -sSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/get.sh | bash
```

## How It Works

The runner supports two modes:

### Polling Mode (Default)
1. **Polls** the coordinator every 30 seconds for new jobs
2. **Fetches credentials** on-demand (never stored locally)
3. **Executes** scraping jobs using Playwright
4. **Reports** results back via API callback

### Realtime Mode (v0.2.0+)
1. **Connects** to Supabase Realtime for instant job dispatch
2. **Tracks presence** so coordinators see active runners
3. **Receives** jobs via websocket broadcast
4. **Reports** results via API callbacks

Both modes restart automatically on crash.

## Manual Installation

If you prefer docker-compose:

```bash
# Clone the repo
git clone https://github.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper.git
cd BayStateScraper

# Create .env file
cat > .env << EOF
SCRAPER_API_URL=https://app.baystatepet.com
SCRAPER_API_KEY=bsr_your_key_here
RUNNER_NAME=$(hostname)
EOF

# Start
docker-compose up -d
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCRAPER_API_URL` | Yes | - | BayStateApp base URL |
| `SCRAPER_API_KEY` | Yes | - | Runner API key (starts with `bsr_`) |
| `RUNNER_NAME` | No | hostname | Identifier for this runner |
| `POLL_INTERVAL` | No | 30 | Seconds between job polls |
| `MAX_JOBS_BEFORE_RESTART` | No | 100 | Restart for memory hygiene |
| `BSR_SUPABASE_REALTIME_KEY` | No | - | Service role key for realtime mode (optional) |
| `HEADLESS` | No | `true` | Set to `false` to run browser in visible mode for debugging |

### Supabase Realtime (Optional)

For real-time job dispatch and runner presence, configure:

```bash
BSR_SUPABASE_REALTIME_KEY=service_role_key_from_supabase
```

Get the key from: **Supabase Dashboard → Settings → API → service_role key**

When configured, runners connect via websocket and receive jobs instantly instead of polling.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       BayStateApp                            │
│  POST /api/scraper/v1/poll      → Returns job or null       │
│  POST /api/scraper/v1/heartbeat → Updates runner status     │
│  GET  /api/scraper/v1/credentials → On-demand credentials   │
│  POST /api/admin/scraping/callback → Receives results       │
│  Supabase Realtime: scrape_jobs INSERT, presence, broadcast  │
└──────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTPS (X-API-Key: bsr_...)
                              │ OR WebSocket (if realtime key configured)
                              │
┌─────────────────────────────┴─────────────────────────────────┐
│  Docker Container (always running)                            │
│  daemon.py polls or connects via realtime → executes → reports│
└───────────────────────────────────────────────────────────────┘
```

## Security

- **Credentials on-demand**: Site passwords are fetched from coordinator when needed, never stored
- **API Key auth**: All requests include `X-API-Key` header
- **HTTPS only**: All communication encrypted in transit
- **No database access**: Runners communicate via API only

## Development

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Run daemon locally
python daemon.py

# Run single job
python runner.py --job-id <uuid>
```

## License

Proprietary - Bay State Pet & Garden Supply
