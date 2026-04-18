"""Command-line interface for BMGateway."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, cast

from . import __version__
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config, validate_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import Device, load_device_registry, validate_devices
from .models import GatewaySnapshot
from .mqtt import DryRunPublisher, MQTTPublisher, Publisher
from .runtime import (
    build_snapshot,
    database_file_path,
    iterations_from_flags,
    sleep_interval,
    state_file_path,
)
from .state_store import (
    fetch_counts,
    fetch_daily_history,
    fetch_monthly_history,
    fetch_recent_history,
    fetch_storage_summary,
    load_snapshot,
    persist_snapshot,
    prune_history,
    write_snapshot,
)
from .web import render_snapshot_html, serve_management, serve_snapshot


def format_main_help() -> str:
    return "\n".join(
        [
            "usage: bm-gateway [--version] [--config PATH] [--verbose] <command>",
            "",
            "Battery monitor gateway contract, runtime, and validation CLI",
            "",
            "Commands:",
            "  config   Show or validate the gateway configuration",
            "  devices  Inspect the configured device registry",
            "  ha       Render the Home Assistant MQTT contract",
            "  history  Inspect persisted raw, daily, or monthly history",
            "  run      Execute the gateway runtime and persist snapshots",
            "  web      Render, serve, or manage the web interface",
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

    config_parser = subparsers.add_parser("config", help="Show or validate the gateway config.")
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_show = config_subparsers.add_parser("show", help="Print the resolved configuration.")
    config_show.add_argument("--json", action="store_true", help="Print structured JSON output.")
    config_validate = config_subparsers.add_parser(
        "validate", help="Validate the gateway config and registry."
    )
    config_validate.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )

    devices_parser = subparsers.add_parser("devices", help="Inspect the configured devices.")
    devices_subparsers = devices_parser.add_subparsers(dest="devices_command")
    devices_list = devices_subparsers.add_parser("list", help="List configured devices.")
    devices_list.add_argument("--json", action="store_true", help="Print structured JSON output.")

    ha_parser = subparsers.add_parser("ha", help="Render Home Assistant contract details.")
    ha_subparsers = ha_parser.add_subparsers(dest="ha_command")
    ha_contract = ha_subparsers.add_parser(
        "contract", help="Show MQTT topics and entity expectations."
    )
    ha_contract.add_argument("--json", action="store_true", help="Print structured JSON output.")
    ha_discovery = ha_subparsers.add_parser(
        "discovery", help="Show or export Home Assistant discovery payloads."
    )
    ha_discovery.add_argument("--json", action="store_true", help="Print structured JSON output.")
    ha_discovery.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write one JSON payload file per discovery topic into this directory.",
    )

    history_parser = subparsers.add_parser("history", help="Inspect persisted history.")
    history_subparsers = history_parser.add_subparsers(dest="history_command")
    history_raw = history_subparsers.add_parser("raw", help="Show recent raw device readings.")
    history_daily = history_subparsers.add_parser("daily", help="Show daily device summaries.")
    history_monthly = history_subparsers.add_parser(
        "monthly", help="Show monthly device summaries."
    )
    history_stats = history_subparsers.add_parser(
        "stats", help="Show storage counts and per-device history ranges."
    )
    history_prune = history_subparsers.add_parser(
        "prune", help="Apply configured retention limits to persisted history."
    )
    for history_command in (history_raw, history_daily, history_monthly):
        history_command.add_argument("--device-id", required=True, help="Device identifier.")
        history_command.add_argument(
            "--json", action="store_true", help="Print structured JSON output."
        )
        history_command.add_argument(
            "--state-dir",
            type=Path,
            default=None,
            help="Override the base directory used for runtime state files.",
        )
        history_command.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of rows returned.",
        )
    for history_command in (history_stats, history_prune):
        history_command.add_argument(
            "--json", action="store_true", help="Print structured JSON output."
        )
        history_command.add_argument(
            "--state-dir",
            type=Path,
            default=None,
            help="Override the base directory used for runtime state files.",
        )

    run_parser = subparsers.add_parser("run", help="Execute the gateway runtime.")
    run_parser.add_argument("--once", action="store_true", help="Run one iteration and exit.")
    run_parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Run a fixed number of iterations instead of forever.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip MQTT publishing and only persist state locally.",
    )
    run_parser.add_argument(
        "--publish-discovery",
        action="store_true",
        help="Publish Home Assistant discovery payloads before state messages.",
    )
    run_parser.add_argument("--json", action="store_true", help="Print the last snapshot as JSON.")
    run_parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the base directory used for runtime state files.",
    )

    web_parser = subparsers.add_parser("web", help="Render or serve the latest snapshot.")
    web_subparsers = web_parser.add_subparsers(dest="web_command")
    web_render = web_subparsers.add_parser("render", help="Render HTML for a snapshot file.")
    web_render.add_argument(
        "--snapshot-file",
        type=Path,
        required=True,
        help="Snapshot JSON file written by `bm-gateway run`.",
    )
    web_serve = web_subparsers.add_parser("serve", help="Serve HTML and JSON status pages.")
    web_serve.add_argument(
        "--snapshot-file",
        type=Path,
        required=True,
        help="Snapshot JSON file written by `bm-gateway run`.",
    )
    web_serve.add_argument("--host", type=str, default="0.0.0.0", help="Bind host.")
    web_serve.add_argument("--port", type=int, default=8080, help="Bind port.")
    web_manage = web_subparsers.add_parser(
        "manage",
        help="Run the host-managed web interface for status, config, and history.",
    )
    web_manage.add_argument("--host", type=str, default="0.0.0.0", help="Bind host.")
    web_manage.add_argument("--port", type=int, default=8080, help="Bind port.")
    web_manage.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the base directory used for runtime state files.",
    )
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


def _load_runtime_or_print_errors(
    path: Path, *, verbose: bool
) -> tuple[AppConfig, list[Device]] | None:
    config, devices, _serialized_devices, errors = _load_runtime(path, verbose=verbose)
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return None
    return config, devices


def _handle_config_show(config: AppConfig, as_json: bool) -> int:
    payload = config.to_dict()
    if as_json:
        _print_json(payload)
        return 0

    print(f"gateway.name: {config.gateway.name}")
    print(f"gateway.timezone: {config.gateway.timezone}")
    print(f"gateway.poll_interval_seconds: {config.gateway.poll_interval_seconds}")
    print(f"gateway.device_registry: {config.device_registry_path}")
    print(f"gateway.reader_mode: {config.gateway.reader_mode}")
    print(f"retention.raw_retention_days: {config.retention.raw_retention_days}")
    print(f"retention.daily_retention_days: {config.retention.daily_retention_days}")
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
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, devices = runtime

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


def _sanitize_discovery_filename(topic: str) -> str:
    return topic.replace("/", "__") + ".json"


def _handle_ha_discovery(
    path: Path,
    *,
    verbose: bool,
    as_json: bool,
    output_dir: Path | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, devices = runtime
    payloads = build_discovery_payloads(config, devices)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for topic, payload in payloads.items():
            target = output_dir / _sanitize_discovery_filename(topic)
            target.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    if as_json:
        _print_json(payloads)
        return 0

    for topic in sorted(payloads):
        print(topic)
    if output_dir is not None:
        print(f"Wrote {len(payloads)} discovery payloads to {output_dir}")
    return 0


def _publisher_for_run(*, dry_run: bool) -> Publisher:
    if dry_run:
        return DryRunPublisher()
    return MQTTPublisher()


def _run_cycle(
    *,
    config: AppConfig,
    devices: list[Device],
    publisher: Publisher,
    publish_discovery: bool,
    state_dir: Path | None,
) -> GatewaySnapshot:
    snapshot = build_snapshot(config, devices)
    try:
        mqtt_connected = publisher.publish_runtime(
            config=config,
            devices=devices,
            snapshot=snapshot,
            publish_discovery=publish_discovery,
        )
    except Exception:
        mqtt_connected = False
    snapshot = GatewaySnapshot(
        generated_at=snapshot.generated_at,
        gateway_name=snapshot.gateway_name,
        active_adapter=snapshot.active_adapter,
        mqtt_enabled=snapshot.mqtt_enabled,
        mqtt_connected=mqtt_connected,
        devices_total=snapshot.devices_total,
        devices_online=snapshot.devices_online,
        poll_interval_seconds=snapshot.poll_interval_seconds,
        devices=snapshot.devices,
    )
    write_snapshot(state_file_path(config, state_dir=state_dir), snapshot)
    database_path = database_file_path(config, state_dir=state_dir)
    persist_snapshot(database_path, snapshot)
    prune_history(
        database_path,
        raw_retention_days=config.retention.raw_retention_days,
        daily_retention_days=config.retention.daily_retention_days,
    )
    return snapshot


def _handle_run(
    path: Path,
    *,
    verbose: bool,
    once: bool,
    iterations: int | None,
    dry_run: bool,
    publish_discovery: bool,
    as_json: bool,
    state_dir: Path | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, devices = runtime
    iteration_limit = iterations_from_flags(once=once, iterations=iterations)
    publisher = _publisher_for_run(dry_run=dry_run)
    completed = 0
    last_snapshot: GatewaySnapshot | None = None

    while iteration_limit is None or completed < iteration_limit:
        last_snapshot = _run_cycle(
            config=config,
            devices=devices,
            publisher=publisher,
            publish_discovery=publish_discovery,
            state_dir=state_dir,
        )
        completed += 1
        if iteration_limit is not None and completed >= iteration_limit:
            break
        sleep_interval(config.gateway.poll_interval_seconds)

    if last_snapshot is None:
        return 1

    if as_json:
        _print_json(last_snapshot.to_dict())
    else:
        print(f"Snapshot written to {state_file_path(config, state_dir=state_dir)}")
        print(f"devices_online: {last_snapshot.devices_online}/{last_snapshot.devices_total}")
        print(f"mqtt_connected: {last_snapshot.mqtt_connected}")
    return 0


def _handle_history(
    path: Path,
    *,
    verbose: bool,
    history_kind: str,
    device_id: str,
    as_json: bool,
    state_dir: Path | None,
    limit: int | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, _devices = runtime
    database_path = database_file_path(config, state_dir=state_dir)
    if history_kind == "raw":
        rows = fetch_recent_history(database_path, device_id=device_id, limit=limit or 200)
    elif history_kind == "daily":
        rows = fetch_daily_history(database_path, device_id=device_id, limit=limit or 365)
    else:
        rows = fetch_monthly_history(database_path, device_id=device_id, limit=limit or 24)

    if as_json:
        _print_json(rows)
        return 0

    for row in rows:
        print(json.dumps(row, sort_keys=True))
    return 0


def _handle_history_stats(
    path: Path,
    *,
    verbose: bool,
    as_json: bool,
    state_dir: Path | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, _devices = runtime
    database_path = database_file_path(config, state_dir=state_dir)
    summary = fetch_storage_summary(database_path)

    if as_json:
        _print_json(summary)
        return 0

    counts = cast(dict[str, int], summary["counts"])
    print(f"gateway_snapshots: {counts['gateway_snapshots']}")
    print(f"device_readings: {counts['device_readings']}")
    print(f"device_daily_rollups: {counts['device_daily_rollups']}")
    for device in cast(list[dict[str, object]], summary["devices"]):
        print(
            f"{device['device_id']}: raw={device['raw_samples']} "
            f"({device['raw_first_ts']} -> {device['raw_last_ts']}), "
            f"daily={device['daily_days']} "
            f"({device['daily_first_day']} -> {device['daily_last_day']})"
        )
    return 0


def _handle_history_prune(
    path: Path,
    *,
    verbose: bool,
    as_json: bool,
    state_dir: Path | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, _devices = runtime
    database_path = database_file_path(config, state_dir=state_dir)
    before = fetch_counts(database_path)
    prune_history(
        database_path,
        raw_retention_days=config.retention.raw_retention_days,
        daily_retention_days=config.retention.daily_retention_days,
    )
    after = fetch_counts(database_path)
    payload = {
        "before": before,
        "after": after,
        "retention": {
            "raw_retention_days": config.retention.raw_retention_days,
            "daily_retention_days": config.retention.daily_retention_days,
        },
    }

    if as_json:
        _print_json(payload)
        return 0

    print(
        "Pruned history with "
        f"raw_retention_days={config.retention.raw_retention_days} "
        f"daily_retention_days={config.retention.daily_retention_days}"
    )
    print(f"device_readings: {before['device_readings']} -> {after['device_readings']}")
    print(
        f"device_daily_rollups: {before['device_daily_rollups']} -> {after['device_daily_rollups']}"
    )
    return 0


def _handle_web_render(snapshot_file: Path) -> int:
    snapshot = load_snapshot(snapshot_file)
    print(render_snapshot_html(snapshot))
    return 0


def _handle_web_serve(*, snapshot_file: Path, host: str, port: int) -> int:
    serve_snapshot(host=host, port=port, snapshot_path=snapshot_file)
    return 0


def _handle_web_manage(*, config_path: Path, host: str, port: int, state_dir: Path | None) -> int:
    serve_management(host=host, port=port, config_path=config_path, state_dir=state_dir)
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
    if args.command == "ha" and args.ha_command == "discovery":
        return _handle_ha_discovery(
            args.config,
            verbose=bool(args.verbose),
            as_json=bool(args.json),
            output_dir=args.output_dir,
        )
    if args.command == "history" and args.history_command in {"raw", "daily", "monthly"}:
        return _handle_history(
            args.config,
            verbose=bool(args.verbose),
            history_kind=args.history_command,
            device_id=args.device_id,
            as_json=bool(args.json),
            state_dir=args.state_dir,
            limit=args.limit,
        )
    if args.command == "history" and args.history_command == "stats":
        return _handle_history_stats(
            args.config,
            verbose=bool(args.verbose),
            as_json=bool(args.json),
            state_dir=args.state_dir,
        )
    if args.command == "history" and args.history_command == "prune":
        return _handle_history_prune(
            args.config,
            verbose=bool(args.verbose),
            as_json=bool(args.json),
            state_dir=args.state_dir,
        )

    if args.command == "run":
        return _handle_run(
            args.config,
            verbose=bool(args.verbose),
            once=bool(args.once),
            iterations=args.iterations,
            dry_run=bool(args.dry_run),
            publish_discovery=bool(args.publish_discovery),
            as_json=bool(args.json),
            state_dir=args.state_dir,
        )

    if args.command == "web":
        if args.web_command == "render":
            return _handle_web_render(args.snapshot_file)
        if args.web_command == "serve":
            return _handle_web_serve(
                snapshot_file=args.snapshot_file,
                host=args.host,
                port=args.port,
            )
        if args.web_command == "manage":
            return _handle_web_manage(
                config_path=args.config,
                host=args.host,
                port=args.port,
                state_dir=args.state_dir,
            )

    print(format_main_help())
    return 0
