"""Command-line interface for BMGateway."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, cast

from . import __version__
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config, validate_config
from .contract import build_contract
from .device_registry import Device, load_device_registry, validate_devices


def format_main_help() -> str:
    return "\n".join(
        [
            "usage: bm-gateway [--version] [--config PATH] [--verbose] <command>",
            "",
            "Battery monitor gateway contract and validation CLI",
            "",
            "Commands:",
            "  config   Show or validate the gateway configuration",
            "  devices  Inspect the configured device registry",
            "  ha       Render the Home Assistant MQTT contract",
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

    config_parser = subparsers.add_parser(
        "config",
        help="Show or validate the gateway config.",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_show = config_subparsers.add_parser(
        "show",
        help="Print the resolved configuration.",
    )
    config_show.add_argument("--json", action="store_true", help="Print structured JSON output.")
    config_validate = config_subparsers.add_parser(
        "validate", help="Validate the gateway config and registry."
    )
    config_validate.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    devices_parser = subparsers.add_parser(
        "devices",
        help="Inspect the configured devices.",
    )
    devices_subparsers = devices_parser.add_subparsers(dest="devices_command")
    devices_list = devices_subparsers.add_parser("list", help="List configured devices.")
    devices_list.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    ha_parser = subparsers.add_parser("ha", help="Render Home Assistant contract details.")
    ha_subparsers = ha_parser.add_subparsers(dest="ha_command")
    ha_contract = ha_subparsers.add_parser(
        "contract", help="Show MQTT topics and entity expectations."
    )
    ha_contract.add_argument("--json", action="store_true", help="Print structured JSON output.")
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_runtime(
    path: Path, *, verbose: bool
) -> tuple[AppConfig, list[Device], list[dict[str, object]], list[str]]:
    config = load_config(path).with_cli_overrides(verbose=verbose)
    config_errors = validate_config(config)
    if config_errors:
        return config, [], [], config_errors

    devices = load_device_registry(config.device_registry_path)
    device_errors = validate_devices(devices)
    serialized_devices = [device.to_dict() for device in devices]
    return config, devices, serialized_devices, device_errors


def _handle_config_show(config: AppConfig, as_json: bool) -> int:
    payload = config.to_dict()
    if as_json:
        _print_json(payload)
        return 0

    print(f"gateway.name: {config.gateway.name}")
    print(f"gateway.timezone: {config.gateway.timezone}")
    print(f"gateway.poll_interval_seconds: {config.gateway.poll_interval_seconds}")
    print(f"gateway.device_registry: {config.device_registry_path}")
    print(f"mqtt.base_topic: {config.mqtt.base_topic}")
    print(f"home_assistant.status_topic: {config.home_assistant.status_topic}")
    print(f"web.bind: {config.web.host}:{config.web.port}")
    return 0


def _handle_config_validate(path: Path, *, verbose: bool, as_json: bool) -> int:
    config, _devices, serialized_devices, errors = _load_runtime(path, verbose=verbose)
    payload = {
        "valid": not errors,
        "errors": errors,
        "device_count": len(serialized_devices),
        "device_registry_path": str(config.device_registry_path),
    }
    if as_json:
        _print_json(payload)
        return 0 if not errors else 2

    if errors:
        print("Configuration is invalid.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    print("Configuration is valid.")
    print(f"{len(serialized_devices)} devices loaded from {config.device_registry_path}")
    return 0


def _handle_devices_list(path: Path, *, verbose: bool, as_json: bool) -> int:
    config, _devices, serialized_devices, errors = _load_runtime(path, verbose=verbose)
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    payload = {
        "device_registry_path": str(config.device_registry_path),
        "devices": serialized_devices,
    }
    if as_json:
        _print_json(payload)
        return 0

    for device in serialized_devices:
        print(
            f"{device['id']}: {device['type']} {device['mac']} "
            f"enabled={str(device['enabled']).lower()}"
        )
    return 0


def _handle_ha_contract(path: Path, *, verbose: bool, as_json: bool) -> int:
    config, devices, _serialized_devices, errors = _load_runtime(path, verbose=verbose)
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    contract = build_contract(config, devices)
    if as_json:
        _print_json(contract)
        return 0

    gateway = cast(dict[str, object], contract["gateway"])
    contract_devices = cast(list[dict[str, object]], contract["devices"])
    print(f"gateway.state_topic: {gateway['state_topic']}")
    print(f"gateway.discovery_topic: {gateway['discovery_topic']}")
    for device in contract_devices:
        print(f"{device['id']}.state_topic: {device['state_topic']}")
        print(f"{device['id']}.discovery_topic: {device['discovery_topic']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list or args_list == ["--help"] or args_list == ["-h"]:
        print(format_main_help())
        return 0

    if args_list == ["--version"]:
        print(__version__)
        return 0

    parser = build_parser()
    args = parser.parse_args(args_list)

    if args.command == "config":
        if args.config_command == "show":
            config = load_config(args.config).with_cli_overrides(verbose=bool(args.verbose))
            return _handle_config_show(config, as_json=bool(args.json))
        if args.config_command == "validate":
            return _handle_config_validate(
                args.config, verbose=bool(args.verbose), as_json=bool(args.json)
            )

    if args.command == "devices" and args.devices_command == "list":
        return _handle_devices_list(
            args.config, verbose=bool(args.verbose), as_json=bool(args.json)
        )

    if args.command == "ha" and args.ha_command == "contract":
        return _handle_ha_contract(
            args.config,
            verbose=bool(args.verbose),
            as_json=bool(args.json),
        )

    print(format_main_help())
    return 0
