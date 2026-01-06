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

- **No database credentials** on runners - all communication via API
- **API keys are hashed** in database (SHA256)
- **RLS policies** ensure runners can only update their own status
