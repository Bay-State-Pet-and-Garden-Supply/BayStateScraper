#!/usr/bin/env python3
"""
Tauri Sidecar Bridge for Bay State Scraper.
Handles IPC communication between Tauri frontend and Python scraper engine.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

def handle_command(command: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route command to appropriate handler."""
    handlers = {
        "get_status": get_status,
        "run_scraper": run_scraper,
        "get_scrapers": get_scrapers,
        "test_scraper": test_scraper,
    }
    
    handler = handlers.get(command)
    if not handler:
        return {"error": f"Unknown command: {command}"}
    
    try:
        return handler(**args)
    except Exception as e:
        return {"error": str(e)}


def get_status() -> dict[str, Any]:
    """Get current runner status."""
    import os
    return {
        "online": True,
        "runner_name": os.environ.get("RUNNER_NAME", "Local Runner"),
        "version": "1.0.0",
        "current_job": None,
        "last_job_time": None,
    }


def run_scraper(scraper_name: str, skus: list[str], headless: bool = True) -> dict[str, Any]:
    """Run a scraper with given SKUs."""
    try:
        from scrapers.main import run_scraping
        
        result = run_scraping(
            scraper_name=scraper_name,
            skus=skus,
            headless=headless,
        )
        
        return {
            "success": True,
            "products_found": len(result.get("products", [])),
            "products": result.get("products", []),
            "errors": result.get("errors", []),
        }
    except Exception as e:
        return {
            "success": False,
            "products_found": 0,
            "products": [],
            "errors": [str(e)],
        }


def get_scrapers() -> dict[str, Any]:
    """Get list of available scrapers."""
    from pathlib import Path
    import yaml
    
    scrapers = []
    configs_dir = Path(__file__).parent / "scrapers" / "configs"
    
    if configs_dir.exists():
        for yaml_file in configs_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    config = yaml.safe_load(f)
                    scrapers.append({
                        "name": config.get("name", yaml_file.stem),
                        "display_name": config.get("display_name", yaml_file.stem.title()),
                        "status": "active" if not config.get("disabled") else "disabled",
                        "last_run": None,
                    })
            except Exception:
                continue
    
    return {"scrapers": scrapers}


def test_scraper(scraper_name: str, sku: str, headless: bool = False) -> dict[str, Any]:
    """Test a single scraper with one SKU in debug mode."""
    return run_scraper(scraper_name, [sku], headless)


def main():
    parser = argparse.ArgumentParser(description="Bay State Scraper Sidecar")
    parser.add_argument("--command", required=True, help="Command to execute")
    parser.add_argument("--args", default="{}", help="JSON arguments")
    
    args = parser.parse_args()
    
    try:
        command_args = json.loads(args.args)
    except json.JSONDecodeError:
        command_args = {}
    
    result = handle_command(args.command, command_args)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
