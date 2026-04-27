"""Command-line interface for BMGateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence, cast

from . import __version__
from .archive_sync import (
    plan_archive_backfill,
    sync_archive_backfill_candidates,
    sync_bm200_device_archive,
    sync_bm300_device_archive,
)
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config, validate_config
from .contract import build_contract, build_discovery_payloads
from .device_registry import Device, device_driver_type, load_device_registry, validate_devices
from .models import GatewaySnapshot
from .mqtt import DryRunPublisher, MQTTPublisher, Publisher
from .protocol_analysis import analyze_history_captures
from .protocol_probe import (
    ProtocolProbeCommand,
    build_bm200_b7_55_deepen_commands,
    build_bm200_b7_55_matrix_commands,
    build_bm200_b7_55_sweep_commands,
    run_protocol_probe,
    utc_timestamp,
)
from .runtime import (
    build_snapshot,
    database_file_path,
    iterations_from_flags,
    sleep_interval,
    state_file_path,
)
from .state_store import (
    fetch_archive_history,
    fetch_counts,
    fetch_daily_history,
    fetch_degradation_report,
    fetch_monthly_history,
    fetch_recent_history,
    fetch_storage_summary,
    fetch_yearly_history,
    persist_snapshot,
    prune_history,
    write_snapshot,
)


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
            "  history  Inspect persisted and imported device history",
            "  protocol Probe bounded read-only BM6/BM7 BLE protocol commands",
            "  run      Execute the gateway runtime and persist snapshots",
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
    history_yearly = history_subparsers.add_parser("yearly", help="Show yearly device summaries.")
    history_compare = history_subparsers.add_parser(
        "compare", help="Show long-term degradation comparison windows."
    )
    history_archive = history_subparsers.add_parser(
        "archive", help="Show imported device-archive history rows."
    )
    history_sync = history_subparsers.add_parser(
        "sync-device",
        help="Download archive history from a supported device into local storage.",
    )
    history_stats = history_subparsers.add_parser(
        "stats", help="Show storage counts and per-device history ranges."
    )
    history_prune = history_subparsers.add_parser(
        "prune", help="Apply configured retention limits to persisted history."
    )
    for history_command in (
        history_raw,
        history_daily,
        history_monthly,
        history_yearly,
        history_archive,
    ):
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
    history_sync.add_argument("--device-id", required=True, help="Device identifier.")
    history_sync.add_argument("--json", action="store_true", help="Print structured JSON output.")
    history_sync.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the base directory used for runtime state files.",
    )
    history_sync.add_argument(
        "--page-count",
        type=int,
        default=3,
        help=(
            "Cumulative history pages to request. BM200/BM6 uses d15505 byte-7; "
            "BM300 Pro/BM7 uses d15505 byte-6."
        ),
    )
    history_compare.add_argument("--device-id", required=True, help="Device identifier.")
    history_compare.add_argument(
        "--json", action="store_true", help="Print structured JSON output."
    )
    history_compare.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the base directory used for runtime state files.",
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
    run_parser.add_argument(
        "--export-usb-otg-now",
        action="store_true",
        help="Force a USB OTG frame-image export during this run.",
    )

    protocol_parser = subparsers.add_parser(
        "protocol", help="Run bounded BM6/BM7 BLE protocol probes."
    )
    protocol_subparsers = protocol_parser.add_subparsers(dest="protocol_command")
    protocol_analyze = protocol_subparsers.add_parser(
        "analyze-history-captures",
        help="Analyze saved protocol probe JSONL history captures offline.",
    )
    protocol_analyze.add_argument(
        "--input",
        action="append",
        type=Path,
        default=[],
        required=True,
        help="Protocol probe JSONL capture path. May be repeated in chronological order.",
    )
    protocol_analyze.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output.",
    )
    protocol_probe = protocol_subparsers.add_parser(
        "probe-history",
        help="Probe known safe live/version/history-candidate commands and print JSONL.",
    )
    protocol_probe.add_argument(
        "--device-id",
        action="append",
        default=[],
        help="Limit the probe to a configured device ID. May be repeated.",
    )
    protocol_probe.add_argument(
        "--command-timeout-seconds",
        type=float,
        default=3.5,
        help="Seconds to wait for notifications after each command.",
    )
    protocol_probe.add_argument(
        "--history-page-limit",
        type=int,
        default=1,
        help="Probe BM200/BM6 d15505 byte-7 history selectors from 01 up to this value.",
    )
    bm200_matrix_group = protocol_probe.add_mutually_exclusive_group()
    bm200_matrix_group.add_argument(
        "--bm200-b7-55-matrix",
        action="store_true",
        help=(
            "Run the controlled BM200/BM6 d15505 b7=55 matrix, mutating one byte "
            "from index 3 through 15 except index 7 to 01."
        ),
    )
    bm200_matrix_group.add_argument(
        "--bm200-b7-55-deepen-byte",
        type=int,
        default=None,
        metavar="INDEX",
        help=(
            "Run the BM200/BM6 b7=55 baseline plus values "
            "02,03,04,10,20,40,80,ff for one byte index from 3 through 15 except 7."
        ),
    )
    bm200_matrix_group.add_argument(
        "--bm200-b7-55-sweep-byte",
        type=int,
        default=None,
        metavar="INDEX",
        help=(
            "Run a BM200/BM6 b7=55 sweep for one byte index from 3 through 15. "
            "Use --sweep-start and --sweep-end to bound the hex value range."
        ),
    )
    protocol_probe.add_argument(
        "--sweep-start",
        default="00",
        help="Inclusive hex start value for --bm200-b7-55-sweep-byte. Default: 00.",
    )
    protocol_probe.add_argument(
        "--sweep-end",
        default="ff",
        help="Inclusive hex end value for --bm200-b7-55-sweep-byte. Default: ff.",
    )

    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _parse_hex_byte(value: str, *, option: str) -> int:
    normalized = value.lower().removeprefix("0x")
    try:
        parsed = int(normalized, 16)
    except ValueError as exc:
        raise ValueError(f"{option} must be a hex byte between 00 and ff") from exc
    if parsed < 0 or parsed > 0xFF:
        raise ValueError(f"{option} must be a hex byte between 00 and ff")
    return parsed


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
    database_path = database_file_path(config, state_dir=state_dir)
    archive_backfill_candidates = (
        plan_archive_backfill(
            config=config,
            database_path=database_path,
            snapshot=snapshot,
        )
        if config.gateway.reader_mode == "live"
        else {}
    )
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
    persist_snapshot(database_path, snapshot)
    if not isinstance(publisher, DryRunPublisher):
        sync_archive_backfill_candidates(
            config=config,
            devices=devices,
            database_path=database_path,
            device_pages=archive_backfill_candidates,
        )
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
    export_usb_otg_now: bool,
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
        runtime = _load_runtime_or_print_errors(path, verbose=verbose)
        if runtime is not None:
            config, devices = runtime
        last_snapshot = _run_cycle(
            config=config,
            devices=devices,
            publisher=publisher,
            publish_discovery=publish_discovery,
            state_dir=state_dir,
        )
        if not dry_run and (config.usb_otg.enabled or export_usb_otg_now):
            from .usb_otg_export import export_due, mark_usb_otg_exported, update_usb_otg_drive

        if not dry_run and (
            export_usb_otg_now
            or (config.usb_otg.enabled and export_due(config=config, state_dir=state_dir))
        ):
            export_result = update_usb_otg_drive(
                config=config,
                devices=devices,
                snapshot=last_snapshot,
                database_path=database_file_path(config, state_dir=state_dir),
                force=export_usb_otg_now,
            )
            if export_result.exported:
                mark_usb_otg_exported(config=config, state_dir=state_dir)
            elif export_usb_otg_now:
                print(f"USB OTG image export failed: {export_result.reason}", file=sys.stderr)
                return 1
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
    elif history_kind == "yearly":
        rows = fetch_yearly_history(database_path, device_id=device_id, limit=limit or 10)
    elif history_kind == "archive":
        rows = fetch_archive_history(database_path, device_id=device_id, limit=limit or 2000)
    else:
        rows = fetch_monthly_history(database_path, device_id=device_id, limit=limit or 24)

    if as_json:
        _print_json(rows)
        return 0

    for row in rows:
        print(json.dumps(row, sort_keys=True))
    return 0


def _handle_history_sync_device(
    path: Path,
    *,
    verbose: bool,
    device_id: str,
    as_json: bool,
    state_dir: Path | None,
    page_count: int,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, devices = runtime
    device = next((item for item in devices if item.id == device_id), None)
    if device is None:
        print(f"Unknown device: {device_id}", file=sys.stderr)
        return 2

    database_path = database_file_path(config, state_dir=state_dir)
    try:
        if device_driver_type(device.type) == "bm300pro":
            payload = sync_bm300_device_archive(
                config=config,
                device=device,
                database_path=database_path,
                page_count=page_count,
            )
        else:
            payload = sync_bm200_device_archive(
                config=config,
                device=device,
                database_path=database_path,
                page_count=page_count,
            )
    except Exception as exc:
        failure = {
            "device_id": device_id,
            "synced": False,
            "error_type": exc.__class__.__name__,
            "error": str(exc) or exc.__class__.__name__,
        }
        if as_json:
            _print_json(failure)
        else:
            print(failure["error"], file=sys.stderr)
        return 1

    payload["synced"] = True
    if as_json:
        _print_json(payload)
        return 0

    print(
        f"Synced archive for {device_id}: "
        f"fetched={payload['fetched']} inserted={payload['inserted']}"
    )
    return 0


def _handle_history_compare(
    path: Path,
    *,
    verbose: bool,
    device_id: str,
    as_json: bool,
    state_dir: Path | None,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, _devices = runtime
    database_path = database_file_path(config, state_dir=state_dir)
    report = fetch_degradation_report(database_path, device_id=device_id)

    if as_json:
        _print_json(report)
        return 0

    print(f"device_id: {report['device_id']}")
    print(f"latest_day: {report['latest_day']}")
    for window in cast(list[dict[str, object]], report["windows"]):
        print(
            f"{window['days']}d: voltage {window['current_avg_voltage']} vs "
            f"{window['previous_avg_voltage']} (delta {window['delta_avg_voltage']}), "
            f"soc {window['current_avg_soc']} vs {window['previous_avg_soc']} "
            f"(delta {window['delta_avg_soc']})"
        )
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


def _handle_protocol_probe_history(
    path: Path,
    *,
    verbose: bool,
    device_ids: Sequence[str],
    command_timeout_seconds: float,
    history_page_limit: int,
    bm200_b7_55_matrix: bool,
    bm200_b7_55_deepen_byte: int | None,
    bm200_b7_55_sweep_byte: int | None,
    sweep_start: str,
    sweep_end: str,
) -> int:
    runtime = _load_runtime_or_print_errors(path, verbose=verbose)
    if runtime is None:
        return 2
    config, devices = runtime
    known_ids = {device.id for device in devices}
    unknown_ids = sorted(set(device_ids) - known_ids)
    if unknown_ids:
        for device_id in unknown_ids:
            print(f"Unknown device: {device_id}", file=sys.stderr)
        return 2
    commands: tuple[ProtocolProbeCommand, ...] | None = None
    if bm200_b7_55_matrix:
        commands = build_bm200_b7_55_matrix_commands()
    elif bm200_b7_55_deepen_byte is not None:
        try:
            commands = build_bm200_b7_55_deepen_commands(byte_index=bm200_b7_55_deepen_byte)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    elif bm200_b7_55_sweep_byte is not None:
        try:
            commands = build_bm200_b7_55_sweep_commands(
                byte_index=bm200_b7_55_sweep_byte,
                start=_parse_hex_byte(sweep_start, option="--sweep-start"),
                end=_parse_hex_byte(sweep_end, option="--sweep-end"),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    def emit(event: dict[str, object]) -> None:
        event.setdefault("ts", utc_timestamp())
        print(json.dumps(event, sort_keys=True), flush=True)

    try:
        asyncio.run(
            run_protocol_probe(
                devices=devices,
                device_ids=device_ids,
                adapter=config.bluetooth.adapter,
                scan_timeout_seconds=config.bluetooth.scan_timeout_seconds,
                connect_timeout_seconds=config.bluetooth.connect_timeout_seconds,
                command_timeout_seconds=command_timeout_seconds,
                history_page_limit=history_page_limit,
                commands=commands,
                emit=emit,
            )
        )
    except KeyboardInterrupt:
        print("Protocol probe interrupted.", file=sys.stderr)
        return 130
    return 0


def _handle_protocol_analyze_history_captures(
    *,
    inputs: Sequence[Path],
    as_json: bool,
) -> int:
    missing = [path for path in inputs if not path.exists()]
    if missing:
        for path in missing:
            print(f"Capture not found: {path}", file=sys.stderr)
        return 2
    report = analyze_history_captures(list(inputs))
    if as_json:
        _print_json(report)
        return 0
    print(f"Analyzed {len(report['captures'])} capture file(s).")
    for command in report["commands"]:
        print(
            f"{command['selector']}: records={command['record_count']} "
            f"plausible={command['plausible_count']} markers={command['marker_count']} "
            f"events={command['event_counts']}"
        )
    if report["overlaps"]:
        print("Overlaps:")
        for overlap in report["overlaps"]:
            print(
                f"{overlap['selector']}: {overlap['classification']} "
                f"old_in_new={overlap['old_in_new_offset']} "
                f"best_run={overlap['best_run_length']} "
                f"old_offset={overlap['best_run_old_offset']} "
                f"new_offset={overlap['best_run_new_offset']}"
            )
    if report["selector_recommendations"]:
        print("Stitch recommendations:")
        for recommendation in report["selector_recommendations"]:
            print(
                f"{recommendation['selector']}: {recommendation['status']} "
                f"({recommendation['reason']})"
            )
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
    if args.command == "history" and args.history_command in {
        "raw",
        "daily",
        "monthly",
        "yearly",
        "archive",
    }:
        return _handle_history(
            args.config,
            verbose=bool(args.verbose),
            history_kind=args.history_command,
            device_id=args.device_id,
            as_json=bool(args.json),
            state_dir=args.state_dir,
            limit=args.limit,
        )
    if args.command == "history" and args.history_command == "compare":
        return _handle_history_compare(
            args.config,
            verbose=bool(args.verbose),
            device_id=args.device_id,
            as_json=bool(args.json),
            state_dir=args.state_dir,
        )
    if args.command == "history" and args.history_command == "sync-device":
        return _handle_history_sync_device(
            args.config,
            verbose=bool(args.verbose),
            device_id=args.device_id,
            as_json=bool(args.json),
            state_dir=args.state_dir,
            page_count=args.page_count,
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

    if args.command == "protocol" and args.protocol_command == "probe-history":
        return _handle_protocol_probe_history(
            args.config,
            verbose=bool(args.verbose),
            device_ids=args.device_id,
            command_timeout_seconds=args.command_timeout_seconds,
            history_page_limit=args.history_page_limit,
            bm200_b7_55_matrix=bool(args.bm200_b7_55_matrix),
            bm200_b7_55_deepen_byte=args.bm200_b7_55_deepen_byte,
            bm200_b7_55_sweep_byte=args.bm200_b7_55_sweep_byte,
            sweep_start=args.sweep_start,
            sweep_end=args.sweep_end,
        )
    if args.command == "protocol" and args.protocol_command == "analyze-history-captures":
        return _handle_protocol_analyze_history_captures(
            inputs=args.input,
            as_json=bool(args.json),
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
            export_usb_otg_now=bool(args.export_usb_otg_now),
        )

    print(format_main_help())
    return 0
