from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from bm_gateway.config import (
    AppConfig,
    BluetoothConfig,
    GatewayConfig,
    HomeAssistantConfig,
    MQTTConfig,
    RetentionConfig,
    WebConfig,
)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        source_path=tmp_path / "gateway.toml",
        device_registry_path=tmp_path / "devices.toml",
        gateway=GatewayConfig(reader_mode="live", data_dir="data"),
        bluetooth=BluetoothConfig(),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
    )


def test_append_audit_event_writes_jsonl_and_prunes_old_files(tmp_path: Path) -> None:
    from bm_gateway.audit_log import append_audit_event

    config = _config(tmp_path)
    state_dir = tmp_path / "state"
    log_dir = state_dir / "runtime" / "audit"
    log_dir.mkdir(parents=True)
    stale_file = log_dir / "2026-01-30.jsonl"
    stale_file.write_text('{"stale":true}\n', encoding="utf-8")

    target = append_audit_event(
        config=config,
        state_dir=state_dir,
        source="runtime",
        trigger="automatic",
        action="run_cycle_completed",
        status="completed",
        details={"devices_online": 4, "devices_total": 5},
        now=datetime.fromisoformat("2026-05-01T12:00:00+02:00"),
    )

    assert target == log_dir / "2026-05-01.jsonl"
    payloads = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert payloads == [
        {
            "action": "run_cycle_completed",
            "details": {"devices_online": 4, "devices_total": 5},
            "source": "runtime",
            "status": "completed",
            "timestamp": "2026-05-01T12:00:00+02:00",
            "trigger": "automatic",
        }
    ]
    assert stale_file.exists() is False
