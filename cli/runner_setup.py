#!/usr/bin/env python3
"""
Bay State Scraper - Runner Setup CLI

Standalone script for setting up a scraper runner.
No git clone required - downloaded via curl.

Usage:
    python runner_setup.py           # Interactive setup
    python runner_setup.py login     # Re-authenticate
    python runner_setup.py status    # Check connection status
"""

from __future__ import annotations

import json
import os
import platform
import sys
import getpass
from pathlib import Path
from typing import Optional

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
CREDENTIALS_FILE = CONFIG_DIR / ".credentials"

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


def load_credentials() -> tuple[str, str]:
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            data = json.load(f)
            return data.get("email", ""), data.get("password", "")
    return "", ""


def save_credentials(email: str, password: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"email": email, "password": password}, f)
    os.chmod(CREDENTIALS_FILE, 0o600)


def clear_screen():
    os.system("cls" if platform.system() == "Windows" else "clear")


def print_header():
    header = Panel(
        "[bold blue]Bay State Scraper[/bold blue] - Runner Setup",
        subtitle="v1.0.0",
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


def prompt_supabase_config() -> tuple[str, str]:
    config = load_config()

    console.print("\n[dim]Supabase configuration (from your BayStateApp admin).[/dim]")

    supabase_url = Prompt.ask(
        "Supabase URL", default=config.get("supabase_url", "https://xxx.supabase.co")
    )

    anon_key = Prompt.ask(
        "Supabase Anon Key", default=config.get("supabase_anon_key", "")
    )

    return supabase_url.rstrip("/"), anon_key


def prompt_credentials() -> tuple[str, str]:
    console.print("\n[bold]Runner Credentials[/bold]")
    console.print(
        "[dim]Get these from Admin Panel > Scraper Network > Runner Accounts[/dim]\n"
    )

    existing_email, existing_password = load_credentials()

    email = Prompt.ask("Email", default=existing_email or "")

    if existing_password:
        console.print(
            "[dim]Password saved. Press Enter to keep it, or type a new one.[/dim]"
        )
        password = getpass.getpass("Password: ") or existing_password
    else:
        password = getpass.getpass("Password: ")

    return email, password


def prompt_runner_name() -> str:
    config = load_config()
    default_name = config.get("runner_name", platform.node())

    console.print(
        "\n[dim]A unique name for this runner (e.g., 'office-mac', 'garage-pi')[/dim]"
    )
    return Prompt.ask("Runner name", default=default_name)


def authenticate(
    supabase_url: str, anon_key: str, email: str, password: str
) -> Optional[str]:
    auth_url = f"{supabase_url}/auth/v1/token?grant_type=password"

    try:
        response = httpx.post(
            auth_url,
            headers={
                "Content-Type": "application/json",
                "apikey": anon_key,
            },
            json={"email": email, "password": password},
            timeout=15,
        )

        if response.status_code == 200:
            return response.json()["access_token"]
        else:
            error = response.json().get("error_description", "Authentication failed")
            console.print(f"[red]Auth error: {error}[/red]")
            return None

    except httpx.ConnectError:
        console.print("[red]Could not connect to Supabase[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Auth error: {e}[/red]")
        return None


def register_runner(api_url: str, token: str, runner_name: str) -> bool:
    register_url = f"{api_url}/api/admin/scraper-network/runners/register"

    try:
        response = httpx.post(
            register_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
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


def test_connection(api_url: str) -> bool:
    try:
        response = httpx.get(f"{api_url}/api/admin/scraper-network/health", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def command_login():
    clear_screen()
    print_header()

    console.print("[bold]Login to Bay State Scraper Network[/bold]\n")

    config = load_config()

    supabase_url = config.get("supabase_url")
    anon_key = config.get("supabase_anon_key")

    if not supabase_url or not anon_key:
        supabase_url, anon_key = prompt_supabase_config()
        config["supabase_url"] = supabase_url
        config["supabase_anon_key"] = anon_key
        save_config(config)

    email, password = prompt_credentials()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Authenticating...", total=None)

        token = authenticate(supabase_url, anon_key, email, password)

        if token:
            progress.update(task, description="[green]✓ Authentication successful")
            save_credentials(email, password)
            return token
        else:
            progress.update(task, description="[red]✗ Authentication failed")
            return None


def command_status():
    config = load_config()

    console.print("\n[bold]Runner Status[/bold]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Runner Name", config.get("runner_name", "[dim]Not set[/dim]"))
    table.add_row("API URL", config.get("api_url", "[dim]Not set[/dim]"))
    table.add_row("Config Dir", str(CONFIG_DIR))

    email, _ = load_credentials()
    table.add_row("Logged in as", email or "[dim]Not logged in[/dim]")

    console.print(table)

    api_url = config.get("api_url")
    if api_url:
        console.print("\n[dim]Testing connection...[/dim]")
        if test_connection(api_url):
            console.print("[green]✓ API connection OK[/green]")
        else:
            console.print("[yellow]⚠ Could not reach API[/yellow]")

    console.print()


def command_setup():
    clear_screen()
    print_header()

    config = load_config()

    api_url = prompt_api_url()
    config["api_url"] = api_url

    supabase_url, anon_key = prompt_supabase_config()
    config["supabase_url"] = supabase_url
    config["supabase_anon_key"] = anon_key

    runner_name = prompt_runner_name()
    config["runner_name"] = runner_name

    save_config(config)

    email, password = prompt_credentials()

    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Testing API connection...", total=None)

        if test_connection(api_url):
            progress.update(task, description="[green]✓ API connection OK")
        else:
            progress.update(
                task, description="[yellow]⚠ Could not reach API (is it running?)"
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Authenticating...", total=None)

        token = authenticate(supabase_url, anon_key, email, password)

        if token:
            progress.update(task, description="[green]✓ Authentication successful")
            save_credentials(email, password)
        else:
            progress.update(task, description="[red]✗ Authentication failed")
            console.print(
                "\n[yellow]Check your credentials and try again with:[/yellow]"
            )
            console.print("  python runner_setup.py login\n")
            return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Registering runner...", total=None)

        if register_runner(api_url, token, runner_name):
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
    console.print("  2. To reconfigure or check status:")
    console.print("     python runner_setup.py status")
    console.print("     python runner_setup.py login\n")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "setup":
        command_setup()
    elif args[0] == "login":
        command_login()
    elif args[0] == "status":
        command_status()
    elif args[0] in ["-h", "--help", "help"]:
        console.print(__doc__)
    else:
        console.print(f"[red]Unknown command: {args[0]}[/red]")
        console.print("Usage: python runner_setup.py [setup|login|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
