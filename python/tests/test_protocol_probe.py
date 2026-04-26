from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from bm_gateway import cli
from bm_gateway.device_registry import Device
from bm_gateway.protocol_probe import (
    ProtocolProbeCommand,
    ProtocolProbeTarget,
    decode_probe_packet,
    encrypt_probe_payload,
    run_protocol_probe,
    safe_probe_commands,
    target_for_device,
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


def test_run_protocol_probe_uses_enabled_selected_devices() -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.targets: list[ProtocolProbeTarget] = []

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
                commands,
                adapter,
                scan_timeout_seconds,
                connect_timeout_seconds,
                command_timeout_seconds,
                emit,
            )
            self.targets.append(target)

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
            transport=transport,
            emit=events.append,
        )
    )

    assert [target.id for target in transport.targets] == ["two"]
    assert events[0]["event"] == "probe_start"
    assert events[0]["device_count"] == 1
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


def test_cli_help_mentions_protocol_command(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main([])

    captured = capsys.readouterr()
    assert result == 0
    assert "protocol" in captured.out
