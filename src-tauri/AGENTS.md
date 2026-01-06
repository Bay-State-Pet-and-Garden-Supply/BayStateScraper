# TAURI DESKTOP APP

**Context:** Cross-platform desktop runner with Python sidecar integration.

## OVERVIEW
Tauri v2 application wrapping the Python scraper engine. Provides secure credential storage, one-click browser installation, and wizard-based onboarding for distributed runner nodes.

**Stack:** Rust, Tauri v2, React (Vite), Tailwind v3, Python sidecar (PyInstaller).

## STRUCTURE
```
src-tauri/
├── src/
│   ├── main.rs            # Entry point, plugin registration
│   ├── commands.rs        # IPC bridge (setup, scraper, browser)
│   ├── storage.rs         # JSON settings persistence
│   └── keychain.rs        # OS keychain for API keys
├── tauri.conf.json        # Sidecar definitions, build config
└── Cargo.toml             # Rust dependencies

../ui/                      # Frontend (separate directory)
├── src/
│   ├── components/        # SetupWizard, ChromiumInstaller
│   └── lib/               # Tauri invoke wrappers
└── tailwind.config.js     # Tailwind v3 with brand colors
```

## IPC COMMANDS (Rust → Frontend)
| Command | Purpose |
|---------|---------|
| `save_api_key` | Validate and store bsr_* key in OS keychain |
| `install_chromium` | Spawn Python process for Playwright browser setup |
| `run_scraper` | Execute sidecar with SKUs and config |
| `test_connection` | Health check against coordinator API |

## PYTHON SIDECAR
- **Entry**: `sidecar_bridge.py` (project root)
- **Packaging**: PyInstaller via `scraper_sidecar.spec`
- **Communication**: JSON over stdin/stdout
- **Naming**: Target-specific binaries (e.g., `scraper-sidecar-aarch64-apple-darwin`)

## EVENTS (Rust → UI)
| Event | Purpose |
|-------|---------|
| `chromium-progress` | Browser install progress (0-100, status, message) |

## CONVENTIONS
- **Credentials**: Always use OS keychain (`keyring` crate), never plaintext
- **Sidecar Rebuild**: Run `pyinstaller scraper_sidecar.spec` after Python changes
- **Resource Management**: Playwright browsers in user data dir, not bundled

## ANTI-PATTERNS
- **NO** storing API keys in config files
- **NO** bundling Chromium in app binary
- **NO** synchronous sidecar calls blocking UI
- **NO** hardcoded paths (use Tauri's app data APIs)
