#!/usr/bin/env python3
"""
Bay State Scraper - Runner Installation Wizard

Interactive CLI tool for setting up a new scraper runner.
Walks users through configuration and validates the setup.

Usage:
    python install.py
    # or
    ./install.py
"""

from __future__ import annotations

import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Optional

# Ensure we can import from scraper_backend if running from repo root
sys.path.insert(0, str(Path(__file__).parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text
    from rich import print as rprint
except ImportError:
    print("Installing required dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text
    from rich import print as rprint

console = Console()

# Constants
ENV_FILE = Path(__file__).parent / "scraper_backend" / ".env"
REQUIREMENTS_FILE = Path(__file__).parent / "scraper_backend" / "requirements.txt"


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if platform.system() == "Windows" else "clear")


def print_header():
    """Print the installation wizard header."""
    header = Text()
    header.append("Bay State Scraper", style="bold blue")
    header.append(" - Runner Installation Wizard", style="dim")

    console.print(Panel(header, subtitle="v1.0.0", border_style="blue"))
    console.print()


def check_prerequisites() -> dict[str, bool]:
    """Check system prerequisites."""
    checks = {}

    py_version = sys.version_info
    checks["python"] = py_version >= (3, 9)

    # Docker
    checks["docker"] = shutil.which("docker") is not None

    # Git
    checks["git"] = shutil.which("git") is not None

    # pip
    checks["pip"] = shutil.which("pip") is not None or shutil.which("pip3") is not None

    return checks


def display_prerequisites(checks: dict[str, bool]) -> bool:
    """Display prerequisite check results."""
    console.print("[bold]Checking prerequisites...[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Status", width=4)
    table.add_column("Item")
    table.add_column("Details", style="dim")

    py_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    table.add_row(
        "[green]" if checks["python"] else "[red]",
        "Python 3.9+",
        f"Found: {py_version}"
        if checks["python"]
        else f"Found: {py_version} (need 3.9+)",
    )

    table.add_row(
        "[green]" if checks["docker"] else "[yellow]",
        "Docker",
        "Installed" if checks["docker"] else "Not found (optional for local dev)",
    )

    table.add_row(
        "[green]" if checks["git"] else "[red]",
        "Git",
        "Installed" if checks["git"] else "Not found",
    )

    table.add_row(
        "[green]" if checks["pip"] else "[red]",
        "pip",
        "Installed" if checks["pip"] else "Not found",
    )

    console.print(table)
    console.print()

    # Only Python and pip are hard requirements
    return checks["python"] and checks["pip"]


def install_dependencies() -> bool:
    """Install Python dependencies."""
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

            progress.update(task, description="[green] Dependencies installed")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return False

    return True


def install_playwright() -> bool:
    """Install Playwright browsers."""
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

            progress.update(task, description="[green] Playwright browsers installed")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return False

    return True


def get_existing_config() -> dict[str, str]:
    """Read existing .env configuration if it exists."""
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
    """Interactive configuration wizard."""
    console.print("\n[bold]Runner Configuration[/bold]")
    console.print("Enter the configuration for this runner.\n")

    existing = get_existing_config()
    config = {}

    # Runner Name
    default_name = existing.get("RUNNER_NAME", platform.node())
    config["RUNNER_NAME"] = Prompt.ask("  Runner name", default=default_name)

    # API URL
    console.print("\n[dim]The API URL is where your BayStateApp is running.[/dim]")
    default_url = existing.get("SCRAPER_API_URL", "http://localhost:3000")
    config["SCRAPER_API_URL"] = Prompt.ask("  BayStateApp API URL", default=default_url)

    # Supabase Configuration
    console.print(
        "\n[dim]Supabase credentials (from your BayStateApp .env.local)[/dim]"
    )

    # Try to auto-detect from BayStateApp
    app_env = Path(__file__).parent.parent / "BayStateApp" / ".env.local"
    app_config = {}
    if app_env.exists():
        with open(app_env) as f:
            for line in f:
                line = line.strip()
                if "NEXT_PUBLIC_SUPABASE_URL" in line:
                    app_config["SUPABASE_URL"] = line.split("=", 1)[1].strip()
                elif "NEXT_PUBLIC_SUPABASE_ANON_KEY" in line:
                    app_config["SUPABASE_ANON_KEY"] = line.split("=", 1)[1].strip()

    if app_config:
        console.print("  [green] Found Supabase config in BayStateApp[/green]")

    default_supabase_url = existing.get("SUPABASE_URL") or app_config.get(
        "SUPABASE_URL", ""
    )
    config["SUPABASE_URL"] = Prompt.ask(
        "  Supabase URL", default=default_supabase_url or "https://xxx.supabase.co"
    )

    default_anon_key = existing.get("SUPABASE_ANON_KEY") or app_config.get(
        "SUPABASE_ANON_KEY", ""
    )
    config["SUPABASE_ANON_KEY"] = Prompt.ask(
        "  Supabase Anon Key", default=default_anon_key or "your-anon-key"
    )

    # Runner Credentials
    console.print(
        "\n[dim]Runner credentials (from Admin Panel > Scraper Network > Runner Accounts)[/dim]"
    )
    console.print(
        "[dim]If you don't have credentials yet, you can get them after setup.[/dim]"
    )

    default_email = existing.get("RUNNER_EMAIL", "")
    config["RUNNER_EMAIL"] = Prompt.ask(
        "  Runner Email", default=default_email or "runner@example.com"
    )

    default_password = existing.get("RUNNER_PASSWORD", "")
    config["RUNNER_PASSWORD"] = Prompt.ask(
        "  Runner Password", default=default_password or "", password=True
    )

    return config


def save_config(config: dict[str, str]) -> bool:
    """Save configuration to .env file."""
    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(ENV_FILE, "w") as f:
            f.write("# Bay State Scraper - Runner Configuration\n")
            f.write("# Generated by install.py\n\n")

            f.write("# Runner Identity\n")
            f.write(f"RUNNER_NAME={config['RUNNER_NAME']}\n\n")

            f.write("# API Configuration\n")
            f.write(f"SCRAPER_API_URL={config['SCRAPER_API_URL']}\n\n")

            f.write("# Supabase Configuration\n")
            f.write(f"SUPABASE_URL={config['SUPABASE_URL']}\n")
            f.write(f"SUPABASE_ANON_KEY={config['SUPABASE_ANON_KEY']}\n\n")

            f.write("# Runner Credentials\n")
            f.write(f"RUNNER_EMAIL={config['RUNNER_EMAIL']}\n")
            f.write(f"RUNNER_PASSWORD={config['RUNNER_PASSWORD']}\n")

        console.print(f"\n[green] Configuration saved to {ENV_FILE}[/green]")
        return True

    except Exception as e:
        console.print(f"[red]Error saving configuration: {e}[/red]")
        return False


def test_connection(config: dict[str, str]) -> bool:
    """Test connection to the API."""
    console.print("\n[bold]Testing connection...[/bold]")

    # Set environment variables for the test
    for key, value in config.items():
        os.environ[key] = value

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Connecting to API...", total=None)

        import httpx

        try:
            # Test basic connectivity
            api_url = config["SCRAPER_API_URL"].rstrip("/")
            response = httpx.get(
                f"{api_url}/api/admin/scraper-network/health", timeout=10
            )

            if response.status_code == 200:
                progress.update(task, description="[green] API connection successful")
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

    # Test authentication if credentials provided
    if (
        config.get("RUNNER_EMAIL")
        and config.get("RUNNER_PASSWORD")
        and "example.com" not in config["RUNNER_EMAIL"]
    ):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Testing authentication...", total=None)

            try:
                from scraper_backend.core.api_client import ScraperAPIClient

                client = ScraperAPIClient(
                    api_url=config["SCRAPER_API_URL"],
                    supabase_url=config["SUPABASE_URL"],
                    runner_email=config["RUNNER_EMAIL"],
                    runner_password=config["RUNNER_PASSWORD"],
                )

                # This will attempt to authenticate
                client._authenticate()
                progress.update(task, description="[green] Authentication successful")

            except Exception as e:
                progress.update(task, description=f"[yellow]⚠ Auth failed: {e}")
                console.print(
                    "[dim]You may need to create runner credentials in the admin panel.[/dim]"
                )
                return False
    else:
        console.print("[dim]Skipping auth test - no credentials configured yet.[/dim]")

    return True


def register_runner(config: dict[str, str]) -> bool:
    """Register this runner with the BayStateApp coordinator."""
    console.print("\n[bold]Registering runner...[/bold]")

    import httpx

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Authenticating and registering...", total=None)

        try:
            supabase_url = config["SUPABASE_URL"].rstrip("/")
            auth_url = f"{supabase_url}/auth/v1/token?grant_type=password"

            auth_response = httpx.post(
                auth_url,
                headers={
                    "Content-Type": "application/json",
                    "apikey": config["SUPABASE_ANON_KEY"],
                },
                json={
                    "email": config["RUNNER_EMAIL"],
                    "password": config["RUNNER_PASSWORD"],
                },
                timeout=15,
            )

            if auth_response.status_code != 200:
                error_msg = auth_response.json().get("error_description", "Auth failed")
                progress.update(
                    task, description=f"[red]✗ Authentication failed: {error_msg}"
                )
                return False

            token = auth_response.json()["access_token"]
            progress.update(task, description="[green]✓ Authenticated")

        except Exception as e:
            progress.update(task, description=f"[red]✗ Auth error: {e}")
            return False

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Registering with coordinator...", total=None)

        try:
            api_url = config["SCRAPER_API_URL"].rstrip("/")
            register_url = f"{api_url}/api/admin/scraper-network/runners/register"

            register_response = httpx.post(
                register_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
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

            if register_response.status_code == 200:
                result = register_response.json()
                progress.update(
                    task,
                    description=f"[green]✓ {result.get('message', 'Registered successfully')}",
                )
                return True
            else:
                error = register_response.json().get("error", "Registration failed")
                progress.update(task, description=f"[red]✗ {error}")
                return False

        except httpx.ConnectError:
            progress.update(task, description="[yellow]⚠ Could not connect to API")
            return False
        except Exception as e:
            progress.update(task, description=f"[red]✗ Error: {e}")
            return False


def print_next_steps(config: dict[str, str], registered: bool = False):
    """Print next steps after installation."""
    console.print("\n")
    console.print(
        Panel("[bold green] Installation Complete![/bold green]", border_style="green")
    )

    console.print("\n[bold]Next Steps:[/bold]\n")

    steps = [
        (
            "1",
            "Get runner credentials",
            "Go to Admin Panel > Scraper Network > Runner Accounts",
        ),
        ("2", "Update credentials", f"Edit {ENV_FILE} with your credentials"),
        ("3", "Start the runner", "Run: ./run_local_job.sh --job-id <JOB_ID>"),
    ]

    if registered:
        steps = [
            ("1", "Runner is ready!", f"Registered as '{config['RUNNER_NAME']}'"),
            ("2", "Run a test job", "./run_local_job.sh --job-id test-123"),
            (
                "3",
                "View in admin",
                f"{config['SCRAPER_API_URL']}/admin/scraper-network",
            ),
        ]
    elif config.get("RUNNER_PASSWORD") and "example" not in config.get(
        "RUNNER_EMAIL", ""
    ):
        steps = [
            ("1", "Verify BayStateApp is running", config["SCRAPER_API_URL"]),
            ("2", "Run a test job", "./run_local_job.sh --job-id test-123"),
        ]

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Step", style="bold cyan")
    table.add_column("Action")
    table.add_column("Details", style="dim")

    for step in steps:
        table.add_row(*step)

    console.print(table)

    console.print("\n[dim]For Docker deployment, see README.md[/dim]")
    console.print(
        "[dim]For GitHub Actions setup, configure secrets in your repository.[/dim]\n"
    )


def main():
    """Main installation wizard."""
    clear_screen()
    print_header()

    # Step 1: Prerequisites
    checks = check_prerequisites()
    if not display_prerequisites(checks):
        console.print(
            "[red]Please install the required prerequisites and try again.[/red]"
        )
        sys.exit(1)

    if not Confirm.ask("Continue with installation?", default=True):
        console.print("Installation cancelled.")
        sys.exit(0)

    # Step 2: Install dependencies
    if not install_dependencies():
        console.print("[red]Failed to install dependencies.[/red]")
        sys.exit(1)

    # Step 3: Install Playwright
    if Confirm.ask("\nInstall Playwright browsers?", default=True):
        if not install_playwright():
            console.print(
                "[yellow]Playwright installation failed. You can install it later with:[/yellow]"
            )
            console.print("  python -m playwright install chromium")

    # Step 4: Configure runner
    console.print()
    if Confirm.ask("Configure runner now?", default=True):
        config = configure_runner()

        if not save_config(config):
            sys.exit(1)

        registered = False
        has_credentials = config.get("RUNNER_PASSWORD") and "example" not in config.get(
            "RUNNER_EMAIL", ""
        )

        if has_credentials:
            if Confirm.ask("\nTest connection and register runner?", default=True):
                if test_connection(config):
                    registered = register_runner(config)
        else:
            console.print(
                "\n[dim]Skipping connection test - no credentials configured yet.[/dim]"
            )

        print_next_steps(config, registered=registered)
    else:
        console.print("\n[dim]You can configure the runner later by running:[/dim]")
        console.print("  python install.py")
        console.print(f"\n[dim]Or manually edit: {ENV_FILE}[/dim]\n")


if __name__ == "__main__":
    main()
