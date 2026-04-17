"""Command-line interface for BMGateway."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config


def format_main_help() -> str:
    description = (
        "Battery monitor gateway mono-repo with Python CLI/service, "
        "Home Assistant integration, Raspberry Pi setup, and web interface"
    )
    return "\n".join(
        [
            "usage: bm-gateway [--version] [--config PATH] [--verbose] <command>",
            "",
            description,
            "",
            "Commands:",
            "  info      Show resolved configuration and runtime metadata",
            "",
            "Run `bm-gateway <command> --help` for command-specific help.",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the installed version and exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Optional config file. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode for this run.",
    )

    subparsers = parser.add_subparsers(dest="command")

    info_parser = subparsers.add_parser(
        "info",
        help="Show resolved configuration and runtime metadata.",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    return parser


def _info_payload(config: AppConfig, config_path: Path) -> dict[str, object]:
    return {
        "project_name": "BMGateway",
        "cli_name": "bm-gateway",
        "package_name": "bm_gateway",
        "version": __version__,
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "config": asdict(config),
    }


def _handle_info(config: AppConfig, config_path: Path, as_json: bool) -> int:
    payload = _info_payload(config=config, config_path=config_path)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"project_name: {payload['project_name']}")
    print(f"cli_name: {payload['cli_name']}")
    print(f"package_name: {payload['package_name']}")
    print(f"version: {payload['version']}")
    print(f"config_path: {payload['config_path']}")
    print(f"config_exists: {payload['config_exists']}")
    print(f"app_name: {config.app_name}")
    print(f"default_output: {config.default_output}")
    print(f"verbose: {config.verbose}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv or [])
    if not args_list or args_list == ["--help"] or args_list == ["-h"]:
        print(format_main_help())
        return 0

    if args_list == ["--version"]:
        print(__version__)
        return 0

    parser = build_parser()
    args = parser.parse_args(args_list)
    config = load_config(args.config).with_cli_overrides(verbose=args.verbose)

    if args.command == "info":
        as_json = bool(getattr(args, "json", False))
        return _handle_info(config=config, config_path=args.config, as_json=as_json)

    print(format_main_help())
    return 0
