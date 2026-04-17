"""Snapshot persistence for BMGateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from .models import GatewaySnapshot


def write_snapshot(path: Path, snapshot: GatewaySnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def load_snapshot(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
