from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Final

RUNTIME_TIMEOUT_SECONDS: Final[float] = 20.0


def _write_example_files(tmp_path: Path) -> Path:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "bm200_house"',
                'type = "bm200"',
                'name = "BM200 House"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "gateway.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'name = "BMGateway"',
                'timezone = "Europe/Rome"',
                "poll_interval_seconds = 15",
                'device_registry = "devices.toml"',
                'data_dir = "data"',
                'reader_mode = "fake"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
                "scan_timeout_seconds = 8",
                "connect_timeout_seconds = 10",
                "",
                "[mqtt]",
                "enabled = true",
                'host = "mqtt.local"',
                "port = 1883",
                'username = "homeassistant"',
                'password = "secret"',
                'base_topic = "bm_gateway"',
                'discovery_prefix = "homeassistant"',
                "retain_discovery = true",
                "retain_state = false",
                "",
                "[home_assistant]",
                "enabled = true",
                'status_topic = "homeassistant/status"',
                'gateway_device_id = "bm_gateway"',
                "",
                "[web]",
                "enabled = true",
                'host = "127.0.0.1"',
                "port = 8080",
                "",
                "[retention]",
                "raw_retention_days = 180",
                "daily_retention_days = 0",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    return env


def _run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=_runtime_env(),
        check=False,
        capture_output=True,
        text=True,
        timeout=RUNTIME_TIMEOUT_SECONDS,
    )


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _wait_for_http(url: str) -> None:
    deadline = time.monotonic() + RUNTIME_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as error:  # pragma: no cover - transient startup timing
            last_error = error
            time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def _http_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=RUNTIME_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post_form(url: str, fields: dict[str, str]) -> tuple[int, str]:
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=RUNTIME_TIMEOUT_SECONDS) as response:
        return response.status, response.read().decode("utf-8")


def _module_command(config_path: Path, *args: str) -> list[str]:
    return [sys.executable, "-m", "bm_gateway", "--config", str(config_path), *args]


def _script_command(config_path: Path, *args: str) -> list[str]:
    return ["uv", "run", "bm-gateway", "--config", str(config_path), *args]


def test_module_entrypoint_runs_fake_runtime_end_to_end(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    validate = _run_command(_module_command(config_path, "config", "validate"), cwd=tmp_path)
    assert validate.returncode == 0, validate.stderr
    assert "Configuration is valid." in validate.stdout

    run_once = _run_command(
        _module_command(
            config_path,
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
            "--json",
        ),
        cwd=tmp_path,
    )
    assert run_once.returncode == 0, run_once.stderr
    run_payload = json.loads(run_once.stdout)
    assert run_payload["devices_online"] == 1
    assert run_payload["devices"][0]["driver"] == "bm200"

    history = _run_command(
        _module_command(
            config_path,
            "history",
            "stats",
            "--state-dir",
            str(state_dir),
            "--json",
        ),
        cwd=tmp_path,
    )
    assert history.returncode == 0, history.stderr
    history_payload = json.loads(history.stdout)
    assert history_payload["counts"]["gateway_snapshots"] == 1
    assert history_payload["devices"][0]["device_id"] == "bm200_house"


def test_console_script_runs_fake_runtime_end_to_end(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    run_once = _run_command(
        _script_command(
            config_path,
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
        ),
        cwd=tmp_path,
    )
    assert run_once.returncode == 0, run_once.stderr
    assert "Snapshot written to" in run_once.stdout

    history = _run_command(
        _script_command(
            config_path,
            "history",
            "daily",
            "--device-id",
            "bm200_house",
            "--state-dir",
            str(state_dir),
            "--json",
        ),
        cwd=tmp_path,
    )
    assert history.returncode == 0, history.stderr
    history_payload = json.loads(history.stdout)
    assert history_payload[0]["device_id"] == "bm200_house"
    assert history_payload[0]["samples"] == 1


def test_web_serve_and_manage_work_end_to_end_with_fake_runtime(tmp_path: Path) -> None:
    config_path = _write_example_files(tmp_path)
    state_dir = tmp_path / "state"

    run_once = _run_command(
        _module_command(
            config_path,
            "run",
            "--once",
            "--dry-run",
            "--state-dir",
            str(state_dir),
        ),
        cwd=tmp_path,
    )
    assert run_once.returncode == 0, run_once.stderr

    snapshot_path = state_dir / "runtime" / "latest_snapshot.json"
    serve_port = _pick_free_port()
    serve_process = subprocess.Popen(
        [
            *(_module_command(config_path, "web", "serve")),
            "--snapshot-file",
            str(snapshot_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(serve_port),
        ],
        cwd=tmp_path,
        env=_runtime_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_http(f"http://127.0.0.1:{serve_port}/api/status")
        status_payload = _http_json(f"http://127.0.0.1:{serve_port}/api/status")
        assert isinstance(status_payload, dict)
        assert status_payload["devices_online"] == 1
    finally:
        serve_process.terminate()
        serve_process.wait(timeout=5)

    manage_port = _pick_free_port()
    manage_process = subprocess.Popen(
        [
            *(_module_command(config_path, "web", "manage")),
            "--host",
            "127.0.0.1",
            "--port",
            str(manage_port),
            "--state-dir",
            str(state_dir),
        ],
        cwd=tmp_path,
        env=_runtime_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{manage_port}"
        _wait_for_http(f"{base_url}/api/status")

        status_payload = _http_json(f"{base_url}/api/status")
        devices_payload = _http_json(f"{base_url}/api/devices")
        contract_payload = _http_json(f"{base_url}/api/ha/contract")
        storage_payload = _http_json(f"{base_url}/api/storage")
        history_payload = _http_json(
            f"{base_url}/api/history?device_id=bm200_house&kind=monthly&limit=24"
        )
        config_payload = _http_json(f"{base_url}/api/config")

        assert isinstance(status_payload, dict)
        assert isinstance(devices_payload, dict)
        assert isinstance(contract_payload, dict)
        assert isinstance(storage_payload, dict)
        assert isinstance(history_payload, list)
        assert isinstance(config_payload, dict)

        assert status_payload["devices_online"] == 1
        assert devices_payload["devices"][0]["id"] == "bm200_house"
        assert contract_payload["gateway"]["state_topic"] == "bm_gateway/gateway/state"
        assert storage_payload["counts"]["device_readings"] == 1
        assert history_payload[0]["device_id"] == "bm200_house"

        connection = sqlite3.connect(state_dir / "runtime" / "gateway.db")
        try:
            before_gateway_count = connection.execute(
                "SELECT COUNT(*) FROM gateway_snapshots"
            ).fetchone()
        finally:
            connection.close()
        assert before_gateway_count == (1,)

        status_code, _response_body = _http_post_form(f"{base_url}/actions/run-once", {})
        assert status_code == 200

        connection = sqlite3.connect(state_dir / "runtime" / "gateway.db")
        try:
            after_gateway_count = connection.execute(
                "SELECT COUNT(*) FROM gateway_snapshots"
            ).fetchone()
        finally:
            connection.close()
        assert after_gateway_count == (2,)

        config_text = str(config_payload["config_toml"]).replace(
            "raw_retention_days = 180",
            "raw_retention_days = 90",
        )
        devices_text = str(config_payload["devices_toml"])
        config_status, config_response = _http_post_form(
            f"{base_url}/config",
            {
                "config_toml": config_text,
                "devices_toml": devices_text,
            },
        )
        assert config_status == 200
        assert "Configuration saved" in config_response
        assert "raw_retention_days = 90" in config_path.read_text(encoding="utf-8")

        prune_status, prune_response = _http_post_form(f"{base_url}/actions/prune-history", {})
        assert prune_status == 200
        assert "History pruned" in prune_response
    finally:
        manage_process.terminate()
        manage_process.wait(timeout=5)
