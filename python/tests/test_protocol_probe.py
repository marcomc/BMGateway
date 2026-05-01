from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from bm_gateway import cli
from bm_gateway.device_registry import Device
from bm_gateway.protocol_probe import (
    ProtocolProbeCommand,
    ProtocolProbeTarget,
    build_bm200_b7_55_deepen_commands,
    build_bm200_b7_55_matrix_commands,
    build_bm200_b7_55_sweep_commands,
    build_probe_commands,
    decode_probe_packet,
    encrypt_probe_payload,
    run_protocol_probe,
    safe_probe_commands,
    summarize_d15505_probe_packets,
    target_for_device,
)


def _write_probe_capture(path: Path, *, command: str, records: list[str]) -> None:
    path.write_text(
        "\n".join(
            [
                '{"event":"probe_start","ts":"2026-04-27T18:00:00+00:00"}',
                (
                    '{"event":"command_result","ts":"2026-04-27T18:00:10+00:00",'
                    f'"command":"{command}","packets":['
                    '{"plaintext":"d1550506710000000000000000000000"},'
                    f'{{"plaintext":"{"".join(records)}"}}'
                    "]}"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_safe_probe_commands_are_bounded_d155_commands() -> None:
    commands = safe_probe_commands()

    assert [command.name for command in commands] == [
        "live_d15507",
        "version_d15501",
        "hist_d15505_zero",
        "hist_d15505_b3_01",
        "hist_d15505_b4_01",
        "hist_d15505_b5_01",
        "hist_d15505_b6_01",
        "hist_d15505_b7_01",
    ]
    assert all(command.plaintext.startswith(bytes.fromhex("d155")) for command in commands)


def test_build_probe_commands_extends_b6_and_b7_history_selectors() -> None:
    commands = build_probe_commands(history_page_limit=4)

    assert [command.name for command in commands[-6:]] == [
        "hist_d15505_b6_02",
        "hist_d15505_b6_03",
        "hist_d15505_b6_04",
        "hist_d15505_b7_02",
        "hist_d15505_b7_03",
        "hist_d15505_b7_04",
    ]
    assert [command.plaintext.hex() for command in commands[-6:]] == [
        "d1550500000002000000000000000000",
        "d1550500000003000000000000000000",
        "d1550500000004000000000000000000",
        "d1550500000000020000000000000000",
        "d1550500000000030000000000000000",
        "d1550500000000040000000000000000",
    ]


def test_build_probe_commands_rejects_unbounded_history_limit() -> None:
    with pytest.raises(ValueError, match="history_page_limit"):
        build_probe_commands(history_page_limit=256)


def test_build_bm200_b7_55_matrix_commands_mutates_one_byte_at_a_time() -> None:
    commands = build_bm200_b7_55_matrix_commands()

    assert [command.name for command in commands] == [
        "bm6_hist_d15505_b7_55_baseline",
        "bm6_hist_d15505_b7_55_b3_01",
        "bm6_hist_d15505_b7_55_b4_01",
        "bm6_hist_d15505_b7_55_b5_01",
        "bm6_hist_d15505_b7_55_b6_01",
        "bm6_hist_d15505_b7_55_b8_01",
        "bm6_hist_d15505_b7_55_b9_01",
        "bm6_hist_d15505_b7_55_b10_01",
        "bm6_hist_d15505_b7_55_b11_01",
        "bm6_hist_d15505_b7_55_b12_01",
        "bm6_hist_d15505_b7_55_b13_01",
        "bm6_hist_d15505_b7_55_b14_01",
        "bm6_hist_d15505_b7_55_b15_01",
    ]
    assert commands[0].plaintext.hex() == "d1550500000000550000000000000000"
    assert commands[1].plaintext.hex() == "d1550501000000550000000000000000"
    assert commands[5].plaintext.hex() == "d1550500000000550100000000000000"


def test_build_bm200_b7_55_deepen_commands_varies_selected_byte() -> None:
    commands = build_bm200_b7_55_deepen_commands(byte_index=6)

    assert [command.name for command in commands] == [
        "bm6_hist_d15505_b7_55_baseline",
        "bm6_hist_d15505_b7_55_b6_02",
        "bm6_hist_d15505_b7_55_b6_03",
        "bm6_hist_d15505_b7_55_b6_04",
        "bm6_hist_d15505_b7_55_b6_10",
        "bm6_hist_d15505_b7_55_b6_20",
        "bm6_hist_d15505_b7_55_b6_40",
        "bm6_hist_d15505_b7_55_b6_80",
        "bm6_hist_d15505_b7_55_b6_ff",
    ]
    assert commands[1].plaintext.hex() == "d1550500000002550000000000000000"
    assert commands[-1].plaintext.hex() == "d15505000000ff550000000000000000"


def test_build_bm200_b7_55_sweep_commands_covers_requested_range() -> None:
    commands = build_bm200_b7_55_sweep_commands(byte_index=6, start=0x05, end=0x08)

    assert [command.name for command in commands] == [
        "bm6_hist_d15505_b7_55_b6_05",
        "bm6_hist_d15505_b7_55_b6_06",
        "bm6_hist_d15505_b7_55_b6_07",
        "bm6_hist_d15505_b7_55_b6_08",
    ]
    assert [command.plaintext.hex() for command in commands] == [
        "d1550500000005550000000000000000",
        "d1550500000006550000000000000000",
        "d1550500000007550000000000000000",
        "d1550500000008550000000000000000",
    ]


def test_build_bm200_b7_55_sweep_commands_can_sweep_byte_7_selector() -> None:
    commands = build_bm200_b7_55_sweep_commands(byte_index=7, start=0x54, end=0x56)

    assert [command.name for command in commands] == [
        "bm6_hist_d15505_b7_55_b7_54",
        "bm6_hist_d15505_b7_55_b7_55",
        "bm6_hist_d15505_b7_55_b7_56",
    ]
    assert [command.plaintext.hex() for command in commands] == [
        "d1550500000000540000000000000000",
        "d1550500000000550000000000000000",
        "d1550500000000560000000000000000",
    ]


@pytest.mark.parametrize(
    ("byte_index", "start", "end"),
    [(2, 0, 1), (16, 0, 1), (4, -1, 1), (4, 0, 256), (4, 5, 4)],
)
def test_build_bm200_b7_55_sweep_commands_rejects_invalid_range(
    byte_index: int,
    start: int,
    end: int,
) -> None:
    with pytest.raises(ValueError, match="sweep"):
        build_bm200_b7_55_sweep_commands(byte_index=byte_index, start=start, end=end)


@pytest.mark.parametrize("byte_index", [2, 7, 16])
def test_build_bm200_b7_55_deepen_commands_rejects_invalid_byte(byte_index: int) -> None:
    with pytest.raises(ValueError, match="byte_index"):
        build_bm200_b7_55_deepen_commands(byte_index=byte_index)


def test_target_for_device_maps_commercial_types_to_protocol_family() -> None:
    bm200 = Device(id="bm200", type="bm200", name="BM200", mac="AA:BB:CC:DD:EE:01")
    bm300 = Device(id="bm300", type="bm300pro", name="BM300", mac="AA:BB:CC:DD:EE:02")

    assert target_for_device(bm200).family == "bm6"
    assert target_for_device(bm300).family == "bm7"


def test_decode_probe_packet_parses_bm7_live_measurement() -> None:
    plaintext = bytes.fromhex("d15507000e026405b300000000000000")
    encrypted = encrypt_probe_payload("bm7", plaintext)

    packet = decode_probe_packet("bm7", encrypted)

    assert packet.marker == "d15507"
    assert packet.parsed == {
        "temperature_c": 14.0,
        "status_code": 2,
        "state": "charging",
        "soc": 100,
        "voltage": 14.59,
        "rapid_accel": 0,
        "rapid_decel": 0,
    }


def test_decode_probe_packet_parses_bm6_code_two_as_charging() -> None:
    plaintext = bytes.fromhex("d155070014026405b20000000002ffff")
    encrypted = encrypt_probe_payload("bm6", plaintext)

    packet = decode_probe_packet("bm6", encrypted)

    assert packet.marker == "d15507"
    assert packet.parsed is not None
    assert packet.parsed["status_code"] == 2
    assert packet.parsed["state"] == "charging"
    assert packet.parsed["voltage"] == 14.58


def test_decode_probe_packet_splits_concatenated_encrypted_frames() -> None:
    first = bytes.fromhex("5b3640d05b3640d05b3640d05b3640d0")
    second = bytes.fromhex("fffefe00000000000000000000000000")
    encrypted = encrypt_probe_payload("bm7", first) + encrypt_probe_payload("bm7", second)

    packet = decode_probe_packet("bm7", encrypted)

    assert packet.frames == (
        {
            "index": 0,
            "encrypted": encrypt_probe_payload("bm7", first).hex(),
            "plaintext": first.hex(),
            "marker": "5b3640",
            "parsed": None,
        },
        {
            "index": 1,
            "encrypted": encrypt_probe_payload("bm7", second).hex(),
            "plaintext": second.hex(),
            "marker": "fffefe",
            "parsed": None,
        },
    )


def test_summarize_d15505_probe_packets_reports_records_and_estimated_range() -> None:
    header = bytes.fromhex("d1550501000000000000000000000000")
    records = bytes.fromhex("52b5317052a530600000000000000000")
    trailer = bytes.fromhex("fffefe00001100000000000000000000")
    encrypted = (
        encrypt_probe_payload("bm6", header)
        + encrypt_probe_payload("bm6", records)
        + encrypt_probe_payload("bm6", trailer)
    )
    packet = decode_probe_packet("bm6", encrypted)

    summary = summarize_d15505_probe_packets(
        "bm6",
        [packet],
        reference_ts="2026-04-27T16:52:00+02:00",
    )

    assert summary == {
        "payload_bytes": 16,
        "non_empty_payload_bytes": 8,
        "record_count": 2,
        "newest_estimated_ts": "2026-04-27T16:52:00+02:00",
        "oldest_estimated_ts": "2026-04-27T16:50:00+02:00",
        "newest_raw": "52b53170",
        "oldest_raw": "52a53060",
        "frame_count": 3,
        "data_frame_count": 1,
        "headers": ["d1550501000000000000000000000000"],
        "trailers": ["fffefe00001100000000000000000000"],
        "decode_error_count": 0,
    }


def test_summarize_d15505_probe_packets_ignores_short_empty_marker() -> None:
    header = bytes.fromhex("d1550500010000550000000000000000")
    marker = bytes.fromhex("fefefe00000000000000000000000000")
    trailer = bytes.fromhex("fffefe00000c00000000000000000000")
    encrypted = (
        encrypt_probe_payload("bm6", header)
        + encrypt_probe_payload("bm6", marker)
        + encrypt_probe_payload("bm6", trailer)
    )
    packet = decode_probe_packet("bm6", encrypted)

    summary = summarize_d15505_probe_packets(
        "bm6",
        [packet],
        reference_ts="2026-04-27T17:33:03+02:00",
    )

    assert summary["payload_bytes"] == 0
    assert summary["record_count"] == 0
    assert summary["newest_raw"] is None
    assert summary["trailers"] == [
        "fefefe00000000000000000000000000",
        "fffefe00000c00000000000000000000",
    ]


def test_run_protocol_probe_uses_enabled_selected_devices() -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.targets: list[ProtocolProbeTarget] = []
            self.commands: list[ProtocolProbeCommand] = []

        async def probe(
            self,
            *,
            target: ProtocolProbeTarget,
            commands: Sequence[ProtocolProbeCommand],
            adapter: str,
            scan_timeout_seconds: float,
            connect_timeout_seconds: float,
            command_timeout_seconds: float,
            emit: Callable[[dict[str, object]], None],
        ) -> None:
            _ = (
                adapter,
                scan_timeout_seconds,
                connect_timeout_seconds,
                command_timeout_seconds,
                emit,
            )
            self.targets.append(target)
            self.commands.extend(commands)

    devices = [
        Device(id="one", type="bm200", name="One", mac="AA:BB:CC:DD:EE:01"),
        Device(id="two", type="bm300pro", name="Two", mac="AA:BB:CC:DD:EE:02"),
        Device(id="off", type="bm200", name="Off", mac="AA:BB:CC:DD:EE:03", enabled=False),
    ]
    events: list[dict[str, object]] = []
    transport = FakeTransport()

    import asyncio

    asyncio.run(
        run_protocol_probe(
            devices=devices,
            device_ids=["two"],
            adapter="auto",
            scan_timeout_seconds=1,
            connect_timeout_seconds=1,
            command_timeout_seconds=1,
            history_page_limit=3,
            transport=transport,
            emit=events.append,
        )
    )

    assert [target.id for target in transport.targets] == ["two"]
    assert [command.name for command in transport.commands] == [
        command.name for command in build_probe_commands(history_page_limit=3)
    ]
    assert events[0]["event"] == "probe_start"
    assert events[0]["device_count"] == 1
    assert events[0]["command_count"] == 12
    assert events[-1]["event"] == "probe_end"


def test_cli_protocol_probe_rejects_unknown_device(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "known"',
                'type = "bm200"',
                'name = "Known"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "probe-history",
            "--device-id",
            "missing",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "Unknown device: missing" in captured.err


def test_cli_protocol_probe_rejects_invalid_bm200_matrix_deepen_byte(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "known"',
                'type = "bm200"',
                'name = "Known"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "probe-history",
            "--device-id",
            "known",
            "--bm200-b7-55-deepen-byte",
            "7",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "byte_index must be between 3 and 15, excluding 7" in captured.err


def test_cli_protocol_probe_rejects_invalid_bm200_sweep_hex(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "known"',
                'type = "bm200"',
                'name = "Known"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "probe-history",
            "--device-id",
            "known",
            "--bm200-b7-55-sweep-byte",
            "6",
            "--sweep-start",
            "zz",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "--sweep-start must be a hex byte between 00 and ff" in captured.err


def test_cli_protocol_probe_history_serializes_bluetooth_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices_path = tmp_path / "devices.toml"
    devices_path.write_text(
        "\n".join(
            [
                "[[devices]]",
                'id = "known"',
                'type = "bm200"',
                'name = "Known"',
                'mac = "AA:BB:CC:DD:EE:01"',
                "enabled = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[gateway]",
                'device_registry = "devices.toml"',
                "",
                "[bluetooth]",
                'adapter = "auto"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_db = tmp_path / "state" / "runtime" / "gateway.db"
    calls: list[tuple[Path | None, str]] = []
    captured: dict[str, object] = {}

    @contextmanager
    def fake_lock(
        _config: object,
        *,
        operation: str,
        state_dir: Path | None = None,
        timeout_seconds: float = 600.0,
        retry_interval_seconds: float = 0.25,
    ) -> Iterator[dict[str, object]]:
        _ = (timeout_seconds, retry_interval_seconds)
        calls.append((state_dir, operation))
        yield {}

    async def fake_run_protocol_probe(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli, "database_file_path", lambda _config: runtime_db, raising=False)
    monkeypatch.setattr(cli, "exclusive_bluetooth_operation", fake_lock, raising=False)
    monkeypatch.setattr(cli, "run_protocol_probe", fake_run_protocol_probe, raising=False)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "protocol",
            "probe-history",
            "--device-id",
            "known",
        ]
    )

    assert result == 0
    assert calls == [(tmp_path / "state", "protocol_probe:known")]
    assert captured["device_ids"] == ["known"]


def test_cli_protocol_analyze_history_captures_outputs_json_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    _write_probe_capture(
        first,
        command="bm6_hist_d15505_b7_55_b4_0a",
        records=["53055120", "4ee5a080"],
    )
    _write_probe_capture(
        second,
        command="bm6_hist_d15505_b7_55_b4_0a",
        records=["53155120", "53055120", "4ee5a080"],
    )

    result = cli.main(
        [
            "protocol",
            "analyze-history-captures",
            "--input",
            str(first),
            "--input",
            str(second),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert '"selector": "b4_0a"' in captured.out
    assert '"classification": "rolling_window"' in captured.out


def test_cli_help_mentions_protocol_command(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main([])

    captured = capsys.readouterr()
    assert result == 0
    assert "protocol" in captured.out
