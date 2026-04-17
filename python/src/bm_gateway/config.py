"""Configuration support for BMGateway."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "bm-gateway" / "config.toml"


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "BMGateway"
    default_output: str = "text"
    verbose: bool = False

    def with_cli_overrides(self, *, verbose: bool) -> "AppConfig":
        if not verbose:
            return self
        return replace(self, verbose=True)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a TOML table at the root.")
    return data


def load_config(path: Path) -> AppConfig:
    data = _read_toml(path)
    return AppConfig(
        app_name=str(data.get("app_name", "BMGateway")),
        default_output=str(data.get("default_output", "text")),
        verbose=bool(data.get("verbose", False)),
    )
