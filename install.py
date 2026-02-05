#!/usr/bin/env python3
"""
Bay State Scraper - Runner Installation Wizard

Interactive CLI tool for setting up a new scraper runner.
Walks users through configuration and validates the setup.

Usage:
    curl -sSL https://raw.githubusercontent.com/OWNER/BayStateScraper/main/install.py | python3
    # or
    python install.py
"""

from __future__ import annotations

import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Installing required dependencies...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "rich", "httpx", "-q"]
    )
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

console = Console()

ENV_FILE = Path(__file__).parent / ".env"
REQUIREMENTS_FILE = Path(__file__).parent / "requirements.txt"


def clear_screen():
    os.system("cls" if platform.system() == "Windows" else "clear")


def print_header():
    header = Text()
    header.append("Bay State Scraper", style="bold blue")
    header.append(" - Runner Installation Wizard", style="dim")

    console.print(
        Panel(header, subtitle="v2.1.0 (Realtime + API Key Auth)", border_style="blue")
    )
    console.print()


def check_prerequisites() -> dict[str, bool]:
    checks = {}
    py_version = sys.version_info
    checks["python"] = py_version >= (3, 9)
    checks["docker"] = shutil.which("docker") is not None
    checks["git"] = shutil.which("git") is not None
    checks["pip"] = shutil.which("pip") is not None or shutil.which("pip3") is not None
    return checks


def display_prerequisites(checks: dict[str, bool]) -> bool:
    console.print("[bold]Checking prerequisites...[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Status", width=4)
    table.add_column("Item")
    table.add_column("Details", style="dim")

    py_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    table.add_row(
        "[green]✓" if checks["python"] else "[red]✗",
        "Python 3.9+",
        f"Found: {py_version}"
        if checks["python"]
        else f"Found: {py_version} (need 3.9+)",
    )

    table.add_row(
        "[green]✓" if checks["docker"] else "[yellow]○",
        "Docker",
        "Installed" if checks["docker"] else "Not found (optional for local dev)",
    )

    table.add_row(
        "[green]✓" if checks["git"] else "[red]✗",
        "Git",
        "Installed" if checks["git"] else "Not found",
    )

    table.add_row(
        "[green]✓" if checks["pip"] else "[red]✗",
        "pip",
        "Installed" if checks["pip"] else "Not found",
    )

    console.print(table)
    console.print()

    return checks["python"] and checks["pip"]


def install_dependencies() -> bool:
    console.print("\n[bold]Installing Python dependencies...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Installing packages from requirements.txt...", total=None
        )

        try:
            if REQUIREMENTS_FILE.exists():
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "-r",
                        str(REQUIREMENTS_FILE),
                        "-q",
                    ],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    console.print(
                        f"[red]Error installing dependencies:[/red]\n{result.stderr}"
                    )
                    return False

            progress.update(task, description="[green]✓ Dependencies installed")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return False

    return True


def install_playwright() -> bool:
    console.print("\n[bold]Installing Playwright browsers...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading Chromium browser...", total=None)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                console.print(
                    f"[red]Error installing Playwright:[/red]\n{result.stderr}"
                )
                return False

            progress.update(task, description="[green]✓ Playwright browsers installed")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return False

    return True


def get_existing_config() -> dict[str, str]:
    config = {}

    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()

    return config


def configure_runner() -> dict[str, str]:
    console.print("\n[bold]Runner Configuration[/bold]")
    console.print("Enter the configuration for this runner.\n")

    existing = get_existing_config()
    config = {}

    default_name = existing.get("RUNNER_NAME", platform.node())
    config["RUNNER_NAME"] = Prompt.ask("  Runner name", default=default_name)

    console.print("\n[dim]The API URL is where your BayStateApp is running.[/dim]")
    default_url = existing.get("SCRAPER_API_URL", "https://app.baystatepet.com")
    config["SCRAPER_API_URL"] = Prompt.ask("  BayStateApp API URL", default=default_url)

    console.print("\n[bold]API Key[/bold]")
    console.print(
        "[dim]Get this from: Admin Panel > Scraper Network > Runner Accounts[/dim]"
    )
    console.print("[dim]Click 'Create Runner' to generate a new API key.[/dim]\n")

    existing_key = existing.get("SCRAPER_API_KEY", "")
    if existing_key:
        masked = existing_key[:12] + "..." if len(existing_key) > 12 else "***"
        console.print(f"[dim]Current key: {masked}[/dim]")
        if Confirm.ask("Keep existing API key?", default=True):
            config["SCRAPER_API_KEY"] = existing_key
        else:
            config["SCRAPER_API_KEY"] = Prompt.ask(
                "  Paste your API key (starts with bsr_)"
            )
    else:
        config["SCRAPER_API_KEY"] = Prompt.ask(
            "  Paste your API key (starts with bsr_)"
        )

    if config["SCRAPER_API_KEY"] and not config["SCRAPER_API_KEY"].startswith("bsr_"):
        console.print("[yellow]Warning: API key should start with 'bsr_'[/yellow]")

    # Supabase Realtime configuration for real-time job updates
    console.print("\n[bold]Supabase Realtime (Optional)[/bold]")
    console.print("[dim]For real-time job updates and runner presence tracking.[/dim]")
    console.print("[dim]Get the service_role key from:[/dim]")
    console.print(
        "  [dim]- Supabase Dashboard > Settings > API > service_role key[/dim]"
    )
    console.print("[dim]Leave empty to use polling mode instead.[/dim]\n")

    existing_realtime_key = existing.get("BSR_SUPABASE_REALTIME_KEY", "")
    if existing_realtime_key:
        masked = (
            existing_realtime_key[:12] + "..."
            if len(existing_realtime_key) > 12
            else "***"
        )
        console.print(f"[dim]Current key: {masked}[/dim]")
        if Confirm.ask("  Keep existing Realtime key?", default=True):
            config["BSR_SUPABASE_REALTIME_KEY"] = existing_realtime_key
        else:
            config["BSR_SUPABASE_REALTIME_KEY"] = Prompt.ask(
                "  Paste your service_role key (or press Enter to skip)"
            )
    else:
        config["BSR_SUPABASE_REALTIME_KEY"] = Prompt.ask(
            "  Paste your service_role key (or press Enter to skip)"
        )

    return config


def save_config(config: dict[str, str]) -> bool:
    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(ENV_FILE, "w") as f:
            f.write("# Bay State Scraper - Runner Configuration\n")
            f.write("# Generated by install.py\n\n")

            f.write("# Runner Identity\n")
            f.write(f"RUNNER_NAME={config['RUNNER_NAME']}\n\n")

            f.write("# API Configuration\n")
            f.write(f"SCRAPER_API_URL={config['SCRAPER_API_URL']}\n\n")

            f.write("# API Key Authentication\n")
            f.write(f"SCRAPER_API_KEY={config['SCRAPER_API_KEY']}\n")

            # Supabase Realtime (optional)
            if config.get("BSR_SUPABASE_REALTIME_KEY"):
                f.write(
                    "\n# Supabase Realtime (Optional - for real-time job updates)\n"
                )
                f.write(
                    f"BSR_SUPABASE_REALTIME_KEY={config['BSR_SUPABASE_REALTIME_KEY']}\n"
                )
                f.write(
                    "# Required channels: scrape_jobs INSERT, runner-presence, job-broadcast\n"
                )

        os.chmod(ENV_FILE, 0o600)

        console.print(f"\n[green]✓ Configuration saved to {ENV_FILE}[/green]")
        return True

    except Exception as e:
        console.print(f"[red]Error saving configuration: {e}[/red]")
        return False


def test_connection(config: dict[str, str]) -> bool:
    console.print("\n[bold]Testing connection...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Connecting to API...", total=None)

        try:
            api_url = config["SCRAPER_API_URL"].rstrip("/")
            response = httpx.get(
                f"{api_url}/api/admin/scraper-network/health",
                headers={"X-API-Key": config["SCRAPER_API_KEY"]},
                timeout=10,
            )

            if response.status_code == 200:
                progress.update(task, description="[green]✓ API connection successful")
            elif response.status_code == 401:
                progress.update(task, description="[red]✗ Invalid API key")
                return False
            else:
                progress.update(
                    task,
                    description=f"[yellow]⚠ API returned status {response.status_code}",
                )

        except httpx.ConnectError:
            progress.update(
                task,
                description="[yellow]⚠ Could not connect to API (is BayStateApp running?)",
            )
            return False
        except Exception as e:
            progress.update(task, description=f"[yellow]⚠ Connection test failed: {e}")
            return False

    return True


def register_runner(config: dict[str, str]) -> bool:
    console.print("\n[bold]Registering runner...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Registering with coordinator...", total=None)

        try:
            api_url = config["SCRAPER_API_URL"].rstrip("/")
            register_url = f"{api_url}/api/admin/scraper-network/runners/register"

            response = httpx.post(
                register_url,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": config["SCRAPER_API_KEY"],
                },
                json={
                    "runner_name": config["RUNNER_NAME"],
                    "metadata": {
                        "platform": platform.system(),
                        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                        "hostname": platform.node(),
                    },
                },
                timeout=15,
            )

            if response.status_code == 200:
                result = response.json()
                progress.update(
                    task,
                    description=f"[green]✓ {result.get('message', 'Registered successfully')}",
                )
                return True
            elif response.status_code == 401:
                progress.update(task, description="[red]✗ Invalid API key")
                return False
            else:
                error = response.json().get("error", "Registration failed")
                progress.update(task, description=f"[red]✗ {error}")
                return False

        except httpx.ConnectError:
            progress.update(task, description="[yellow]⚠ Could not connect to API")
            return False
        except Exception as e:
            progress.update(task, description=f"[red]✗ Error: {e}")
            return False


def print_next_steps(config: dict[str, str], registered: bool = False):
    console.print("\n")
    console.print(
        Panel("[bold green]✓ Installation Complete![/bold green]", border_style="green")
    )

    console.print("\n[bold]Next Steps:[/bold]\n")

    if registered:
        steps = [
            ("1", "Runner is ready!", f"Registered as '{config['RUNNER_NAME']}'"),
            (
                "2",
                "Run a test job",
                "python -m runner --job-id <JOB_ID>",
            ),
            (
                "3",
                "View in admin",
                f"{config['SCRAPER_API_URL']}/admin/scraper-network",
            ),
        ]
    else:
        steps = [
            ("1", "Get an API key", "Admin Panel > Scraper Network > Runner Accounts"),
            ("2", "Run setup again", "python install.py"),
            ("3", "Or edit config directly", str(ENV_FILE)),
        ]

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Step", style="bold cyan")
    table.add_column("Action")
    table.add_column("Details", style="dim")

    for step in steps:
        table.add_row(*step)

    console.print(table)

    console.print("\n[bold]For GitHub Actions / Docker:[/bold]")
    console.print("[dim]Set these environment variables:[/dim]\n")
    console.print(f"  SCRAPER_API_URL={config['SCRAPER_API_URL']}")
    if config.get("SCRAPER_API_KEY"):
        masked = (
            config["SCRAPER_API_KEY"][:12] + "..."
            if len(config["SCRAPER_API_KEY"]) > 12
            else "***"
        )
        console.print(f"  SCRAPER_API_KEY={masked}")
    console.print(f"  RUNNER_NAME={config['RUNNER_NAME']}")
    if config.get("BSR_SUPABASE_REALTIME_KEY"):
        console.print("  # Supabase Realtime (optional)")
        console.print("  BSR_SUPABASE_REALTIME_KEY=<service_role_key>")
    else:
        console.print("  # BSR_SUPABASE_REALTIME_KEY=<optional - for realtime mode>")
    console.print()


def main():
    clear_screen()
    print_header()

    checks = check_prerequisites()
    if not display_prerequisites(checks):
        console.print(
            "[red]Please install the required prerequisites and try again.[/red]"
        )
        sys.exit(1)

    if not Confirm.ask("Continue with installation?", default=True):
        console.print("Installation cancelled.")
        sys.exit(0)

    if REQUIREMENTS_FILE.exists():
        if not install_dependencies():
            console.print("[red]Failed to install dependencies.[/red]")
            sys.exit(1)

        if Confirm.ask("\nInstall Playwright browsers?", default=True):
            if not install_playwright():
                console.print(
                    "[yellow]Playwright installation failed. You can install it later with:[/yellow]"
                )
                console.print("  python -m playwright install chromium")

    console.print()
    config = configure_runner()

    if not save_config(config):
        sys.exit(1)

    registered = False
    has_api_key = config.get("SCRAPER_API_KEY") and config[
        "SCRAPER_API_KEY"
    ].startswith("bsr_")

    if has_api_key:
        if Confirm.ask("\nTest connection and register runner?", default=True):
            if test_connection(config):
                registered = register_runner(config)
    else:
        console.print(
            "\n[dim]Skipping connection test - no valid API key configured.[/dim]"
        )

    print_next_steps(config, registered=registered)


if __name__ == "__main__":
    main()
