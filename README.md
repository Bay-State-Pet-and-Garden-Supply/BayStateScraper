# BayStateScraper

Distributed scraper runners for Bay State Pet & Garden Supply product data collection.

## NEW: Desktop Application (v1.0)

Bay State Scraper is now a **self-contained desktop application** with:
- Full local UI for debugging and manual scrapes
- Headless mode for GitHub Actions integration
- Self-update capability
- Cross-platform support (Mac, Linux, Windows)

## Project Structure

```
BayStateScraper/
├── src-tauri/          # Tauri Rust backend
│   ├── src/
│   │   ├── main.rs     # Tauri entry point
│   │   └── commands.rs # IPC commands
│   └── tauri.conf.json # Tauri configuration
├── ui/                 # React frontend (Vite + Tailwind)
│   ├── src/
│   │   ├── components/ # Dashboard, Settings, Scrapers
│   │   └── App.tsx
│   └── package.json
├── core/               # Python core engine
├── scrapers/           # Scraper configs and executor
├── api/                # FastAPI debug server
├── utils/              # Debugging and utility tools
├── runner.py           # CLI runner entry point
├── sidecar_bridge.py   # Tauri-Python IPC bridge
└── scraper_sidecar.spec # PyInstaller bundling spec
```

## Quick Start

### Desktop App (Download)

Download the latest release for your platform:

| Platform | Download |
|----------|----------|
| **macOS** (Intel/Apple Silicon) | [Bay.State.Scraper.dmg](https://github.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/releases/latest) |
| **Windows** | [Bay.State.Scraper.msi](https://github.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/releases/latest) |

**First Run (macOS):** Right-click → Open → Confirm (required until app is notarized)

### Desktop App (Development)

```bash
# Install UI dependencies
cd ui && npm install

# Install Rust dependencies and run
cd ../src-tauri && cargo tauri dev
```

### CLI Mode (Existing)

```bash
# Install Python dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Run a job
python -m runner --job-id <JOB_ID>
```

### One-Line Install (Production)

```bash
curl -fsSL https://raw.githubusercontent.com/Bay-State-Pet-and-Garden-Supply/BayStateScraper/main/install.sh | bash
```

### Docker (Headless)

For production environments using Docker or GitHub Actions, use the official image:

```bash
docker pull ghcr.io/bay-state-pet-and-garden-supply/baystatescraper:latest
docker run -e SCRAPER_API_URL=... -e SCRAPER_API_KEY=... baystatescraper
```

## Execution Modes

| Mode | Trigger | UI | Use Case |
|------|---------|-----|----------|
| **Desktop** | Launch app | Full UI | Local debugging, manual scrapes |
| **CLI** | `python -m runner --job-id X` | Terminal output | Scripting, cron jobs |
| **Headless** | GitHub Actions / Docker | None (logs only) | Production scrapes |
| **Daemon** | System service | Tray icon (optional) | Always-on self-hosted runner |

## Building the Desktop App

### macOS / Linux

```bash
# Build the Python sidecar
pip install pyinstaller
pyinstaller scraper_sidecar.spec

# Copy to Tauri binaries directory
cp dist/scraper-sidecar-* src-tauri/binaries/

# Build the app
cd ui && npm run build
cd ../src-tauri && cargo tauri build
```

### Development

```bash
# Start frontend dev server
cd ui && npm run dev

# In another terminal, start Tauri
cd src-tauri && cargo tauri dev
```

## Configuration

Create `.env` in the project root:

```env
RUNNER_NAME=my-runner
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
