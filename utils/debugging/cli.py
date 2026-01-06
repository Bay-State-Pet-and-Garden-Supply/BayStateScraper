#!/usr/bin/env python3
"""
CLI entry point for scraper debugging tools.

Usage:
    # Validate a config
    python -m utils.debugging.cli validate path/to/config.yaml

    # Validate all configs in a directory
    python -m utils.debugging.cli validate-all path/to/configs/

    # Test a selector against a URL
    python -m utils.debugging.cli test-selector "#productTitle" --url "https://amazon.com/dp/..."

    # Test all selectors from a config
    python -m utils.debugging.cli test-config path/to/config.yaml --sku "035585499741"

    # Debug a workflow step by step
    python -m utils.debugging.cli debug path/to/config.yaml --sku "035585499741"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a single config file."""
    from .config_validator import ConfigValidator

    validator = ConfigValidator(strict=args.strict)
    result = validator.validate_file(args.config_path)

    print(result)

    if args.json:
        output = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "config_name": result.config_name,
            "file_path": result.file_path,
        }
        print(json.dumps(output, indent=2))

    return 0 if result.valid else 1


def cmd_validate_all(args: argparse.Namespace) -> int:
    """Validate all configs in a directory."""
    from .config_validator import validate_all_configs

    results = validate_all_configs(args.configs_dir, strict=args.strict)

    total = len(results)
    valid_count = sum(1 for r in results.values() if r.valid)
    invalid_count = total - valid_count

    print(f"\nValidation Results: {valid_count}/{total} valid\n")
    print("-" * 60)

    for filename, result in sorted(results.items()):
        status = "PASS" if result.valid else "FAIL"
        print(f"[{status}] {filename}")
        if not result.valid:
            for error in result.errors[:3]:
                print(f"      ERROR: {error}")
        if result.warnings and args.show_warnings:
            for warning in result.warnings[:3]:
                print(f"      WARN: {warning}")

    print("-" * 60)
    print(f"Total: {total}, Valid: {valid_count}, Invalid: {invalid_count}")

    if args.json:
        output = {
            "total": total,
            "valid": valid_count,
            "invalid": invalid_count,
            "results": {
                filename: {
                    "valid": r.valid,
                    "errors": r.errors,
                    "warnings": r.warnings,
                }
                for filename, r in results.items()
            },
        }
        print(json.dumps(output, indent=2))

    return 0 if invalid_count == 0 else 1


def cmd_test_selector(args: argparse.Namespace) -> int:
    """Test a selector against a URL."""
    from .selector_tester import SelectorTester

    with SelectorTester(headless=args.headless) as tester:
        result = tester.test_selector(
            selector=args.selector,
            url=args.url,
            attribute=args.attribute,
        )

    print(result)
    print()

    if result.success:
        print(f"Found {result.match_count} matches:")
        for match in result.matches:
            print(f"  [{match.get('index')}] <{match.get('tag', '?')}>")
            if "text" in match:
                text_preview = match["text"][:100] if match["text"] else "(empty)"
                print(f"      Text: {text_preview}")
            if "html_preview" in match:
                html_preview = match["html_preview"][:150]
                print(f"      HTML: {html_preview}...")
    else:
        print(f"No matches found. Error: {result.error or 'None'}")

    if args.json:
        output = {
            "selector": result.selector,
            "match_count": result.match_count,
            "matches": result.matches,
            "timing_ms": result.timing_ms,
            "error": result.error,
        }
        print(json.dumps(output, indent=2))

    return 0 if result.success else 1


def cmd_test_config(args: argparse.Namespace) -> int:
    """Test all selectors from a config file."""
    from .selector_tester import SelectorTester

    with SelectorTester(headless=args.headless) as tester:
        result = tester.test_config_selectors(
            config_path=args.config_path,
            sku=args.sku,
        )

    print(result)

    if args.json:
        output = {
            "url": result.url,
            "success_count": result.success_count,
            "fail_count": result.fail_count,
            "page_load_time_ms": result.page_load_time_ms,
            "total_time_ms": result.total_time_ms,
            "results": [
                {
                    "selector": r.selector,
                    "match_count": r.match_count,
                    "timing_ms": r.timing_ms,
                    "error": r.error,
                }
                for r in result.results
            ],
        }
        print(json.dumps(output, indent=2))

    return 0 if result.fail_count == 0 else 1


def cmd_debug(args: argparse.Namespace) -> int:
    """Debug a workflow step by step."""
    from .step_debugger import StepDebugger

    context = {}
    if args.sku:
        context["sku"] = args.sku

    debugger = StepDebugger(
        config_path=args.config_path,
        headless=args.headless,
        context=context,
    )

    try:
        debugger._ensure_executor()

        print("\n" + "=" * 60)
        print("STEP DEBUGGER")
        print("=" * 60)
        print(f"Config: {args.config_path}")
        print(f"Context: {context}")
        print(f"Total steps: {debugger.state.total_steps}")
        print("-" * 60)

        # Show available steps
        steps = debugger.get_workflow_steps()
        print("\nWorkflow Steps:")
        for step in steps:
            print(f"  [{step['index']}] {step['action']}")
            if step["params"]:
                params_preview = str(step["params"])[:60]
                print(f"       params: {params_preview}...")

        print("\n" + "-" * 60)

        if args.run_all:
            # Run all steps
            print("\nRunning all steps...\n")
            results = debugger.run_all(capture_screenshots=args.screenshots)
            for result in results:
                print(result)
            print("\n" + "-" * 60)
            print(
                f"Extracted data: {json.dumps(debugger.get_extracted_data(), indent=2)}"
            )
        elif args.run_to is not None:
            # Run to specific step
            print(f"\nRunning to step {args.run_to}...\n")
            results = debugger.run_to_step(
                args.run_to, capture_screenshots=args.screenshots
            )
            for result in results:
                print(result)
        else:
            # Interactive mode
            print("\nInteractive mode. Commands:")
            print("  s, step     - Execute next step")
            print("  r, run      - Run all remaining steps")
            print("  i, inspect  - Inspect current state")
            print("  t, test     - Test a selector")
            print("  d, data     - Show extracted data")
            print("  save        - Save debug state to files")
            print("  q, quit     - Exit")
            print()

            while True:
                try:
                    cmd = (
                        input(
                            f"[{debugger.current_step_index}/{debugger.state.total_steps}] > "
                        )
                        .strip()
                        .lower()
                    )
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting...")
                    break

                if cmd in ("q", "quit", "exit"):
                    break
                elif cmd in ("s", "step", ""):
                    if debugger.state.workflow_complete:
                        print("Workflow complete.")
                    else:
                        result = debugger.step()
                        print(result)
                elif cmd in ("r", "run"):
                    results = debugger.run_all()
                    for result in results:
                        print(result)
                elif cmd in ("i", "inspect"):
                    state = debugger.inspect_state()
                    print(state.summary())
                elif cmd in ("d", "data"):
                    print(json.dumps(debugger.get_extracted_data(), indent=2))
                elif cmd in ("t", "test"):
                    selector = input("Selector: ").strip()
                    if selector:
                        result = debugger.test_selector(selector)
                        print(f"Matches: {result['match_count']}")
                        for match in result.get("matches", [])[:5]:
                            print(f"  - {match[:100] if match else '(empty)'}")
                elif cmd == "save":
                    path = debugger.save_debug_state()
                    print(f"Saved to: {path}")
                else:
                    print(f"Unknown command: {cmd}")

        # Save final state if requested
        if args.save_state:
            path = debugger.save_debug_state(args.save_state)
            print(f"\nState saved to: {path}")

        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        debugger.close()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Scraper debugging tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a config file")
    validate_parser.add_argument("config_path", help="Path to YAML config file")
    validate_parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors"
    )
    validate_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # validate-all command
    validate_all_parser = subparsers.add_parser(
        "validate-all", help="Validate all configs in directory"
    )
    validate_all_parser.add_argument(
        "configs_dir", help="Directory containing config files"
    )
    validate_all_parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors"
    )
    validate_all_parser.add_argument(
        "--show-warnings", action="store_true", help="Show warnings in output"
    )
    validate_all_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # test-selector command
    test_selector_parser = subparsers.add_parser(
        "test-selector", help="Test a selector against a URL"
    )
    test_selector_parser.add_argument("selector", help="CSS or XPath selector")
    test_selector_parser.add_argument(
        "--url", required=True, help="URL to test against"
    )
    test_selector_parser.add_argument(
        "--attribute", help="Attribute to extract (default: text)"
    )
    test_selector_parser.add_argument(
        "--headless", action="store_true", default=True, help="Run headless"
    )
    test_selector_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # test-config command
    test_config_parser = subparsers.add_parser(
        "test-config", help="Test selectors from a config"
    )
    test_config_parser.add_argument("config_path", help="Path to YAML config file")
    test_config_parser.add_argument("--sku", help="SKU to use for URL template")
    test_config_parser.add_argument(
        "--headless", action="store_true", default=True, help="Run headless"
    )
    test_config_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # debug command
    debug_parser = subparsers.add_parser("debug", help="Debug a workflow step by step")
    debug_parser.add_argument("config_path", help="Path to YAML config file")
    debug_parser.add_argument("--sku", help="SKU for context")
    debug_parser.add_argument(
        "--headless", action="store_true", help="Run headless (default: visible)"
    )
    debug_parser.add_argument(
        "--run-all", action="store_true", help="Run all steps non-interactively"
    )
    debug_parser.add_argument("--run-to", type=int, help="Run to specific step index")
    debug_parser.add_argument(
        "--screenshots", action="store_true", help="Capture screenshots"
    )
    debug_parser.add_argument("--save-state", help="Save final state to directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "validate":
        return cmd_validate(args)
    elif args.command == "validate-all":
        return cmd_validate_all(args)
    elif args.command == "test-selector":
        return cmd_test_selector(args)
    elif args.command == "test-config":
        return cmd_test_config(args)
    elif args.command == "debug":
        return cmd_debug(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
