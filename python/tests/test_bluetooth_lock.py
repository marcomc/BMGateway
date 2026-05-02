from __future__ import annotations

import json
from pathlib import Path

import pytest
from bm_gateway.bluetooth_lock import (
    BluetoothOperationBusyError,
    bluetooth_lock_path,
    exclusive_bluetooth_operation,
)
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
        gateway=GatewayConfig(),
        bluetooth=BluetoothConfig(),
        mqtt=MQTTConfig(),
        home_assistant=HomeAssistantConfig(),
        web=WebConfig(),
        retention=RetentionConfig(),
    )


def test_exclusive_bluetooth_operation_writes_and_clears_holder_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state_dir = tmp_path / "state"
    lock_path = bluetooth_lock_path(config, state_dir=state_dir)

    with exclusive_bluetooth_operation(
        config,
        state_dir=state_dir,
        operation="live_poll:bm300_doc",
    ) as payload:
        holder = json.loads(lock_path.read_text(encoding="utf-8"))
        assert holder["operation"] == "live_poll:bm300_doc"
        assert holder["pid"] == payload["pid"]

    assert lock_path.read_text(encoding="utf-8") == ""


def test_exclusive_bluetooth_operation_reports_current_holder_when_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    state_dir = tmp_path / "state"
    lock_path = bluetooth_lock_path(config, state_dir=state_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"operation": "archive_sync:bm300_doc", "pid": 4242}) + "\n",
        encoding="utf-8",
    )

    def fake_flock(_fd: int, operation: int) -> None:
        if operation & 4:
            raise BlockingIOError

    monkeypatch.setattr("bm_gateway.bluetooth_lock.fcntl.flock", fake_flock)
    monkeypatch.setattr("bm_gateway.bluetooth_lock.sleep", lambda _seconds: None)

    with pytest.raises(BluetoothOperationBusyError) as exc_info:
        with exclusive_bluetooth_operation(
            config,
            state_dir=state_dir,
            operation="live_poll:bm300_doc",
            timeout_seconds=0.0,
            retry_interval_seconds=0.0,
        ):
            pytest.fail("lock acquisition should have timed out")

    message = str(exc_info.value)
    assert "archive_sync:bm300_doc" in message
    assert "4242" in message
