#!/usr/bin/env python3
"""
Bay State Scraper - Runner Setup CLI

Standalone script for setting up a scraper runner.
No git clone required - downloaded via curl.

Usage:
    python runner_setup.py           # Interactive setup
    python runner_setup.py status    # Check connection status
    python runner_setup.py test      # Test API connection
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

try:
    import httpx
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
except ImportError:
    print("Missing dependencies. Run: pip install httpx rich")
    sys.exit(1)

console = Console()

CONFIG_DIR = Path.home() / ".baystate-runner"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API_URL = "https://app.baystatepet.com"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Secure the config file (contains API key)
    os.chmod(CONFIG_FILE, 0o600)


def clear_screen():
    os.system("cls" if platform.system() == "Windows" else "clear")


def print_header():
    header = Panel(
        "[bold blue]Bay State Scraper[/bold blue] - Runner Setup",
        subtitle="v2.0.0 (API Key Auth)",
        border_style="blue",
    )
    console.print(header)
    console.print()


def prompt_api_url() -> str:
    config = load_config()
    current = config.get("api_url", DEFAULT_API_URL)

    console.print("[dim]The API URL is where BayStateApp is running.[/dim]")
    url = Prompt.ask("API URL", default=current)
    return url.rstrip("/")


def prompt_api_key() -> str:
    config = load_config()
    existing = config.get("api_key", "")

    console.print("\n[bold]API Key[/bold]")
    console.print(
        "[dim]Get this from Admin Panel > Scraper Network > Runner Accounts[/dim]\n"
    )

    if existing:
        masked = existing[:12] + "..." + existing[-4:] if len(existing) > 16 else "***"
        console.print(f"[dim]Current key: {masked}[/dim]")
        if Confirm.ask("Keep existing API key?", default=True):
            return existing

    api_key = Prompt.ask("API Key (starts with bsr_)")

    if not api_key.startswith("bsr_"):
        console.print("[yellow]Warning: API key should start with 'bsr_'[/yellow]")

    return api_key


def prompt_runner_name() -> str:
    config = load_config()
    default_name = config.get("runner_name", platform.node())

    console.print(
        "\n[dim]A unique name for this runner (e.g., 'office-mac', 'garage-pi')[/dim]"
    )
    return Prompt.ask("Runner name", default=default_name)


def test_api_connection(api_url: str, api_key: str) -> bool:
    """Test the API connection with the provided credentials."""
    try:
        response = httpx.get(
            f"{api_url}/api/admin/scraper-network/health",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        return response.status_code == 200
    except Exception as e:
        console.print(f"[dim]Connection error: {e}[/dim]")
        return False


def register_runner(api_url: str, api_key: str, runner_name: str) -> bool:
    """Register this runner with the coordinator."""
    register_url = f"{api_url}/api/admin/scraper-network/runners/register"

    try:
        response = httpx.post(
            register_url,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            json={
                "runner_name": runner_name,
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
            console.print(
                f"[green]✓ {result.get('message', 'Registered successfully')}[/green]"
            )
            return True
        else:
            error = response.json().get("error", "Registration failed")
            console.print(f"[red]Registration error: {error}[/red]")
            return False

    except httpx.ConnectError:
        console.print("[yellow]Could not connect to BayStateApp API[/yellow]")
        return False
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return False


def command_status():
    config = load_config()

    console.print("\n[bold]Runner Status[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Runner Name", config.get("runner_name", "[dim]Not set[/dim]"))
    table.add_row("API URL", config.get("api_url", "[dim]Not set[/dim]"))
    table.add_row("Config Dir", str(CONFIG_DIR))

    api_key = config.get("api_key", "")
    if api_key:
        masked = api_key[:12] + "..." if len(api_key) > 12 else "***"
        table.add_row("API Key", masked)
    else:
        table.add_row("API Key", "[dim]Not configured[/dim]")

    console.print(table)

    api_url = config.get("api_url")
    if api_url and api_key:
        console.print("\n[dim]Testing connection...[/dim]")
        if test_api_connection(api_url, api_key):
            console.print("[green]✓ API connection OK[/green]")
        else:
            console.print("[yellow]⚠ Could not reach API or invalid key[/yellow]")

    console.print()


def command_test():
    """Test the API connection and authentication."""
    config = load_config()

    api_url = config.get("api_url")
    api_key = config.get("api_key")

    if not api_url or not api_key:
        console.print("[red]Not configured. Run setup first.[/red]")
        return

    console.print("\n[bold]Testing API Connection[/bold]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Connecting to API...", total=None)

        try:
            response = httpx.get(
                f"{api_url}/api/admin/scraper-network/health",
                headers={"X-API-Key": api_key},
                timeout=10,
            )

            if response.status_code == 200:
                progress.update(task, description="[green]✓ API connection successful")
            elif response.status_code == 401:
                progress.update(task, description="[red]✗ Invalid API key")
            else:
                progress.update(
                    task,
                    description=f"[yellow]⚠ Unexpected status: {response.status_code}",
                )

        except httpx.ConnectError:
            progress.update(task, description="[red]✗ Could not connect to API")
        except Exception as e:
            progress.update(task, description=f"[red]✗ Error: {e}")

    console.print()


def command_setup():
    clear_screen()
    print_header()

    config = load_config()

    api_url = prompt_api_url()
    config["api_url"] = api_url

    runner_name = prompt_runner_name()
    config["runner_name"] = runner_name

    api_key = prompt_api_key()
    config["api_key"] = api_key

    save_config(config)

    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Testing API connection...", total=None)

        if test_api_connection(api_url, api_key):
            progress.update(task, description="[green]✓ API connection OK")
        else:
            progress.update(
                task, description="[yellow]⚠ Could not verify API connection"
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Registering runner...", total=None)

        if register_runner(api_url, api_key, runner_name):
            progress.update(task, description=f"[green]✓ Registered as '{runner_name}'")
        else:
            progress.update(task, description="[yellow]⚠ Registration failed")

    console.print()
    console.print(
        Panel("[bold green]Setup Complete![/bold green]", border_style="green")
    )

    console.print("\n[bold]Next Steps:[/bold]\n")
    console.print(f"  1. View this runner in the admin panel:")
    console.print(f"     {api_url}/admin/scraper-network\n")
    console.print("  2. To check status or test connection:")
    console.print("     python runner_setup.py status")
    console.print("     python runner_setup.py test\n")

    console.print("[bold]Environment Variables for Docker:[/bold]\n")
    console.print(f"  SCRAPER_API_URL={api_url}")
    console.print(f"  SCRAPER_API_KEY={api_key[:20]}...")
    console.print(f"  RUNNER_NAME={runner_name}\n")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "setup":
        command_setup()
    elif args[0] == "status":
        command_status()
    elif args[0] == "test":
        command_test()
    elif args[0] in ["-h", "--help", "help"]:
        console.print(__doc__)
    else:
        console.print(f"[red]Unknown command: {args[0]}[/red]")
        console.print("Usage: python runner_setup.py [setup|status|test]")
        sys.exit(1)


if __name__ == "__main__":
    main()
