#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def setup_environment_from_config(config_json: str | None) -> None:
    if not config_json:
        return
    try:
        config = json.loads(config_json)
        if config.get("api_url"):
            os.environ["SCRAPER_API_URL"] = config["api_url"]
        if config.get("api_key"):
            os.environ["SCRAPER_API_KEY"] = config["api_key"]
        if config.get("runner_name"):
            os.environ["RUNNER_NAME"] = config["runner_name"]
        if config.get("browsers_path"):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = config["browsers_path"]
    except json.JSONDecodeError:
        pass


def install_browser(browsers_path: str | None = None) -> dict[str, Any]:
    if browsers_path:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )

        output_lines = []
        if process.stdout:
            for line in process.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    progress_msg = {"type": "progress", "message": line}
                    print(json.dumps(progress_msg), flush=True)

        return_code = process.wait()
        return {
            "success": return_code == 0,
            "output": output_lines,
            "error": None if return_code == 0 else "Installation failed",
        }
    except Exception as e:
        return {"success": False, "output": [], "error": str(e)}


def check_browser_installed(browsers_path: str | None = None) -> dict[str, Any]:
    if browsers_path:
        path = Path(browsers_path)
    else:
        path = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))

    if not path.exists():
        return {"installed": False, "path": str(path)}

    chromium_dirs = list(path.glob("chromium-*"))
    return {
        "installed": len(chromium_dirs) > 0,
        "path": str(path),
        "browsers": [d.name for d in chromium_dirs],
    }


def handle_command(command: str, args: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "get_status": get_status,
        "run_scraper": run_scraper,
        "get_scrapers": get_scrapers,
        "test_scraper": test_scraper,
        "install_browser": install_browser,
        "check_browser": check_browser_installed,
    }

    handler = handlers.get(command)
    if not handler:
        return {"error": f"Unknown command: {command}"}

    try:
        return handler(**args)
    except Exception as e:
        return {"error": str(e)}


def get_status() -> dict[str, Any]:
    return {
        "online": True,
        "runner_name": os.environ.get("RUNNER_NAME", "Local Runner"),
        "version": "1.0.0",
        "current_job": None,
        "last_job_time": None,
    }


def run_scraper(
    scraper_name: str, skus: list[str], headless: bool = True
) -> dict[str, Any]:
    try:
        from scrapers.main import run_scraping

        result = run_scraping(
            scraper_name=scraper_name,
            skus=skus,
            headless=headless,
        )

        products = result.get("products", []) if result else []
        errors = result.get("errors", []) if result else []

        return {
            "success": True,
            "products_found": len(products),
            "products": products,
            "errors": errors,
        }
    except Exception as e:
        return {
            "success": False,
            "products_found": 0,
            "products": [],
            "errors": [str(e)],
        }


def get_scrapers() -> dict[str, Any]:
    import yaml

    scrapers = []
    configs_dir = Path(__file__).parent / "scrapers" / "configs"

    if configs_dir.exists():
        for yaml_file in configs_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    config = yaml.safe_load(f)
                    if config:
                        scrapers.append(
                            {
                                "name": config.get("name", yaml_file.stem),
                                "display_name": config.get(
                                    "display_name", yaml_file.stem.title()
                                ),
                                "status": "active"
                                if not config.get("disabled")
                                else "disabled",
                                "last_run": None,
                            }
                        )
            except Exception:
                continue

    return {"scrapers": scrapers}


def test_scraper(scraper_name: str, sku: str, headless: bool = False) -> dict[str, Any]:
    return run_scraper(scraper_name, [sku], headless)


def main():
    parser = argparse.ArgumentParser(description="Bay State Scraper Sidecar")
    parser.add_argument("--command", help="Command to execute")
    parser.add_argument("--args", default="{}", help="JSON arguments")
    parser.add_argument("--config", help="JSON config from Tauri")
    parser.add_argument(
        "--install-browser", action="store_true", help="Install Chromium browser"
    )
    parser.add_argument("--browsers-path", help="Path to store browsers")

    args = parser.parse_args()

    setup_environment_from_config(args.config)

    if args.install_browser:
        result = install_browser(args.browsers_path)
        print(json.dumps(result))
        return

    if not args.command:
        print(json.dumps({"error": "No command specified"}))
        return

    try:
        command_args = json.loads(args.args)
    except json.JSONDecodeError:
        command_args = {}

    result = handle_command(args.command, command_args)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
