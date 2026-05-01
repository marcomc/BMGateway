"""Structured audit logging for automatic and manual gateway operations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from .config import AppConfig

AUDIT_LOG_RETENTION_DAYS = 90


def audit_log_directory(config: AppConfig, *, state_dir: Path | None = None) -> Path:
    base_dir = (
        state_dir
        if state_dir is not None
        else (config.source_path.parent / config.gateway.data_dir)
    )
    return base_dir / "runtime" / "audit"


def prune_audit_logs(
    log_dir: Path,
    *,
    now: datetime | None = None,
    retention_days: int = AUDIT_LOG_RETENTION_DAYS,
) -> None:
    active_now = now or datetime.now().astimezone()
    cutoff_date = active_now.date() - timedelta(days=retention_days)
    if not log_dir.exists():
        return
    for path in log_dir.glob("*.jsonl"):
        try:
            file_date = datetime.fromisoformat(path.stem).date()
        except ValueError:
            continue
        if file_date <= cutoff_date:
            path.unlink(missing_ok=True)


def append_audit_event(
    *,
    config: AppConfig,
    source: str,
    trigger: str,
    action: str,
    status: str,
    state_dir: Path | None = None,
    details: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> Path:
    active_now = now or datetime.now().astimezone()
    log_dir = audit_log_directory(config, state_dir=state_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    prune_audit_logs(log_dir, now=active_now)
    payload: dict[str, object] = {
        "timestamp": active_now.isoformat(timespec="seconds"),
        "source": source,
        "trigger": trigger,
        "action": action,
        "status": status,
    }
    if details:
        payload["details"] = dict(details)
    target = log_dir / f"{active_now.date().isoformat()}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    return target
