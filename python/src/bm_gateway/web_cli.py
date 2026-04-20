"""Dedicated web executable for BMGateway."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import DEFAULT_CONFIG_PATH, load_config
from .state_store import load_snapshot
from .web import render_snapshot_html, serve_management, serve_snapshot


def format_main_help() -> str:
    return "\n".join(
        [
            "usage: bm-gateway-web [manage options] | <render|serve|manage> [options]",
            "",
            "Dedicated optional web executable for BMGateway",
            "",
            "Commands:",
            "  manage  Run the host-managed web interface",
            "  serve   Serve HTML and JSON status pages from a snapshot file",
            "  render  Render HTML for a snapshot file",
            "",
            "If no command is provided, manage mode is assumed.",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="command")

    manage = subparsers.add_parser("manage", help="Run the host-managed web interface.")
    manage.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Optional config file. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    manage.add_argument("--host", type=str, default=None, help="Bind host.")
    manage.add_argument("--port", type=int, default=None, help="Bind port.")
    manage.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the base directory used for runtime state files.",
    )

    serve = subparsers.add_parser("serve", help="Serve HTML and JSON status pages.")
    serve.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Optional config file. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    serve.add_argument(
        "--snapshot-file",
        type=Path,
        required=True,
        help="Snapshot JSON file written by `bm-gateway run`.",
    )
    serve.add_argument("--host", type=str, default=None, help="Bind host.")
    serve.add_argument("--port", type=int, default=None, help="Bind port.")

    render = subparsers.add_parser("render", help="Render HTML for a snapshot file.")
    render.add_argument(
        "--snapshot-file",
        type=Path,
        required=True,
        help="Snapshot JSON file written by `bm-gateway run`.",
    )

    return parser


def _normalize_args(args_list: list[str]) -> list[str]:
    commands = {"manage", "serve", "render"}
    if args_list and args_list[0] in commands:
        return args_list
    for index, value in enumerate(args_list):
        if value in commands:
            return [value, *args_list[:index], *args_list[index + 1 :]]
    return ["manage", *args_list]


def run_web_command(
    command: str,
    *,
    config_path: Path | None = None,
    snapshot_file: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    state_dir: Path | None = None,
) -> int:
    if command == "render":
        if snapshot_file is None:
            raise ValueError("snapshot_file is required for render")
        snapshot = load_snapshot(snapshot_file)
        print(render_snapshot_html(snapshot))
        return 0

    active_config_path = config_path or DEFAULT_CONFIG_PATH
    config = load_config(active_config_path)
    resolved_host = host or config.web.host
    resolved_port = port or config.web.port

    if command == "serve":
        if snapshot_file is None:
            raise ValueError("snapshot_file is required for serve")
        serve_snapshot(host=resolved_host, port=resolved_port, snapshot_path=snapshot_file)
        return 0

    if command == "manage":
        serve_management(
            host=resolved_host,
            port=resolved_port,
            config_path=active_config_path,
            state_dir=state_dir,
        )
        return 0

    raise ValueError(f"Unsupported web command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list or args_list == ["--help"] or args_list == ["-h"]:
        print(format_main_help())
        return 0

    if args_list == ["--version"]:
        print(__version__)
        return 0

    parser = build_parser()
    args = parser.parse_args(_normalize_args(args_list))

    return run_web_command(
        args.command,
        config_path=getattr(args, "config", None),
        snapshot_file=getattr(args, "snapshot_file", None),
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        state_dir=getattr(args, "state_dir", None),
    )
