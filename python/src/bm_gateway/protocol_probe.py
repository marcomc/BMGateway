"""Bounded BLE protocol probes for BM6/BM7-family monitors."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from bleak import BleakClient, BleakScanner
from bleak.args.bluez import BlueZClientArgs, BlueZScannerArgs
from Crypto.Cipher import AES

from .device_registry import DEVICE_DRIVER_TYPES, Device
from .drivers.bm200 import BM200_NOTIFY_CHARACTERISTIC, BM200_WRITE_CHARACTERISTIC

ZERO_IV = bytes(16)
BLOCK_SIZE = 16
BM6_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 48, 49, 48, 48, 48, 48, 57])
BM7_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 48, 49, 48, 48, 48, 48, 64])


@dataclass(frozen=True)
class ProtocolProbeCommand:
    name: str
    plaintext: bytes


@dataclass(frozen=True)
class ProtocolProbeTarget:
    id: str
    type: str
    name: str
    mac: str
    family: str


@dataclass(frozen=True)
class DecodedProbePacket:
    encrypted_hex: str
    plaintext_hex: str
    marker: str
    parsed: dict[str, object] | None
    frames: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "encrypted": self.encrypted_hex,
            "plaintext": self.plaintext_hex,
            "marker": self.marker,
            "parsed": self.parsed,
        }
        if self.frames:
            payload["frames"] = list(self.frames)
        return payload


class ProtocolProbeTransport(Protocol):
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
    ) -> None: ...


SAFE_D155_PROBE_COMMANDS = (
    ProtocolProbeCommand("live_d15507", bytes.fromhex("d1550700000000000000000000000000")),
    ProtocolProbeCommand("version_d15501", bytes.fromhex("d1550100000000000000000000000000")),
    ProtocolProbeCommand("hist_d15505_zero", bytes.fromhex("d1550500000000000000000000000000")),
    ProtocolProbeCommand("hist_d15505_b3_01", bytes.fromhex("d1550501000000000000000000000000")),
    ProtocolProbeCommand("hist_d15505_b4_01", bytes.fromhex("d1550500010000000000000000000000")),
    ProtocolProbeCommand("hist_d15505_b5_01", bytes.fromhex("d1550500000100000000000000000000")),
    ProtocolProbeCommand("hist_d15505_b6_01", bytes.fromhex("d1550500000001000000000000000000")),
    ProtocolProbeCommand("hist_d15505_b7_01", bytes.fromhex("d1550500000000010000000000000000")),
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def target_for_device(device: Device) -> ProtocolProbeTarget:
    driver_type = DEVICE_DRIVER_TYPES.get(device.type, device.type)
    if driver_type == "bm200":
        family = "bm6"
    elif driver_type == "bm300pro":
        family = "bm7"
    else:
        family = "unknown"
    return ProtocolProbeTarget(
        id=device.id,
        type=device.type,
        name=device.name,
        mac=device.mac,
        family=family,
    )


def safe_probe_commands() -> tuple[ProtocolProbeCommand, ...]:
    return SAFE_D155_PROBE_COMMANDS


def build_probe_commands(*, history_page_limit: int = 1) -> tuple[ProtocolProbeCommand, ...]:
    if history_page_limit < 1 or history_page_limit > 255:
        raise ValueError("history_page_limit must be between 1 and 255")

    commands = list(SAFE_D155_PROBE_COMMANDS)
    for page in range(2, history_page_limit + 1):
        commands.append(
            ProtocolProbeCommand(
                f"hist_d15505_b6_{page:02x}",
                bytes(
                    [
                        0xD1,
                        0x55,
                        0x05,
                        0x00,
                        0x00,
                        0x00,
                        page,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                    ]
                ),
            )
        )
    for page in range(2, history_page_limit + 1):
        commands.append(
            ProtocolProbeCommand(
                f"hist_d15505_b7_{page:02x}",
                bytes(
                    [
                        0xD1,
                        0x55,
                        0x05,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        page,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                        0x00,
                    ]
                ),
            )
        )
    return tuple(commands)


def _bm200_b7_55_command_name(byte_index: int | None, value: int | None) -> str:
    if byte_index is None or value is None:
        return "bm6_hist_d15505_b7_55_baseline"
    return f"bm6_hist_d15505_b7_55_b{byte_index}_{value:02x}"


def _bm200_b7_55_command(*, byte_index: int | None = None, value: int | None = None) -> bytes:
    command = bytearray.fromhex("d1550500000000550000000000000000")
    if byte_index is not None and value is not None:
        command[byte_index] = value
    return bytes(command)


def _validate_bm200_b7_55_mutation_byte(byte_index: int) -> None:
    if byte_index < 3 or byte_index > 15 or byte_index == 7:
        raise ValueError("byte_index must be between 3 and 15, excluding 7")


def _validate_bm200_b7_55_sweep(byte_index: int, start: int, end: int) -> None:
    if byte_index < 3 or byte_index > 15:
        raise ValueError("sweep byte_index must be between 3 and 15")
    if start < 0 or start > 0xFF or end < 0 or end > 0xFF or start > end:
        raise ValueError("sweep range must be between 00 and ff with start <= end")


def build_bm200_b7_55_matrix_commands() -> tuple[ProtocolProbeCommand, ...]:
    commands = [
        ProtocolProbeCommand(
            _bm200_b7_55_command_name(None, None),
            _bm200_b7_55_command(),
        )
    ]
    for byte_index in range(3, 16):
        if byte_index == 7:
            continue
        commands.append(
            ProtocolProbeCommand(
                _bm200_b7_55_command_name(byte_index, 0x01),
                _bm200_b7_55_command(byte_index=byte_index, value=0x01),
            )
        )
    return tuple(commands)


def build_bm200_b7_55_deepen_commands(*, byte_index: int) -> tuple[ProtocolProbeCommand, ...]:
    _validate_bm200_b7_55_mutation_byte(byte_index)
    values = (0x02, 0x03, 0x04, 0x10, 0x20, 0x40, 0x80, 0xFF)
    return (
        ProtocolProbeCommand(
            _bm200_b7_55_command_name(None, None),
            _bm200_b7_55_command(),
        ),
        *(
            ProtocolProbeCommand(
                _bm200_b7_55_command_name(byte_index, value),
                _bm200_b7_55_command(byte_index=byte_index, value=value),
            )
            for value in values
        ),
    )


def build_bm200_b7_55_sweep_commands(
    *,
    byte_index: int,
    start: int = 0x00,
    end: int = 0xFF,
) -> tuple[ProtocolProbeCommand, ...]:
    _validate_bm200_b7_55_sweep(byte_index, start, end)
    return tuple(
        ProtocolProbeCommand(
            _bm200_b7_55_command_name(byte_index, value),
            _bm200_b7_55_command(byte_index=byte_index, value=value),
        )
        for value in range(start, end + 1)
    )


def protocol_key(family: str) -> bytes:
    if family == "bm6":
        return BM6_AES_KEY
    if family == "bm7":
        return BM7_AES_KEY
    raise ValueError(f"Unsupported protocol family: {family}")


def encrypt_probe_payload(family: str, plaintext: bytes) -> bytes:
    cipher = AES.new(protocol_key(family), AES.MODE_CBC, ZERO_IV)
    return bytes(cipher.encrypt(_pad_payload(plaintext)))


def decrypt_probe_payload(family: str, encrypted: bytes | bytearray) -> bytes:
    cipher = AES.new(protocol_key(family), AES.MODE_CBC, ZERO_IV)
    return bytes(cipher.decrypt(bytes(encrypted)))


def decode_probe_packet(family: str, encrypted: bytes | bytearray) -> DecodedProbePacket:
    encrypted_bytes = bytes(encrypted)
    plaintext = decrypt_probe_payload(family, encrypted_bytes)
    frames = tuple(_decode_probe_frames(family, encrypted_bytes))
    return DecodedProbePacket(
        encrypted_hex=encrypted_bytes.hex(),
        plaintext_hex=plaintext.hex(),
        marker=plaintext[:3].hex(),
        parsed=parse_probe_measurement(family, plaintext),
        frames=frames,
    )


def parse_probe_measurement(family: str, plaintext: bytes) -> dict[str, object] | None:
    if len(plaintext) < 16 or not plaintext.startswith(bytes.fromhex("d15507")):
        return None
    if plaintext[3] == 0xFF:
        return None

    temperature = -float(plaintext[4]) if plaintext[3] == 0x01 else float(plaintext[4])
    status_code = plaintext[5]
    status_map = (
        {0: "normal", 1: "low", 2: "charging"}
        if family == "bm6"
        else {0: "normal", 1: "low", 2: "charging"}
    )
    return {
        "temperature_c": temperature,
        "status_code": status_code,
        "state": status_map.get(status_code, "unknown"),
        "soc": plaintext[6],
        "voltage": ((plaintext[7] << 8) | plaintext[8]) / 100.0,
        "rapid_accel": (plaintext[9] << 8) | plaintext[10],
        "rapid_decel": (plaintext[11] << 8) | plaintext[12],
    }


def _pad_payload(data: bytes) -> bytes:
    size = ((len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
    return data.ljust(size, b"\x00")


def _decode_probe_frames(family: str, encrypted: bytes) -> list[dict[str, object]]:
    if len(encrypted) <= BLOCK_SIZE or len(encrypted) % BLOCK_SIZE != 0:
        return []
    frames: list[dict[str, object]] = []
    for index in range(0, len(encrypted), BLOCK_SIZE):
        frame_encrypted = encrypted[index : index + BLOCK_SIZE]
        frame_plaintext = decrypt_probe_payload(family, frame_encrypted)
        frames.append(
            {
                "index": index // BLOCK_SIZE,
                "encrypted": frame_encrypted.hex(),
                "plaintext": frame_plaintext.hex(),
                "marker": frame_plaintext[:3].hex(),
                "parsed": parse_probe_measurement(family, frame_plaintext),
            }
        )
    return frames


def summarize_d15505_probe_packets(
    family: str,
    packets: Sequence[DecodedProbePacket],
    *,
    reference_ts: str | datetime,
    decode_error_count: int = 0,
) -> dict[str, object]:
    _ = family
    if isinstance(reference_ts, str):
        active_reference_ts = datetime.fromisoformat(reference_ts)
        reference_ts_text = reference_ts
    else:
        active_reference_ts = reference_ts
        reference_ts_text = reference_ts.isoformat(timespec="seconds")

    payload = b""
    headers: list[str] = []
    trailers: list[str] = []
    frame_count = 0
    data_frame_count = 0
    seen_header = False

    for packet in packets:
        plaintext_frames = (
            [
                str(frame["plaintext"])
                for frame in packet.frames
                if isinstance(frame.get("plaintext"), str)
            ]
            if packet.frames
            else [packet.plaintext_hex]
        )
        for plaintext_hex in plaintext_frames:
            frame_count += 1
            plaintext = bytes.fromhex(plaintext_hex)
            if plaintext.startswith(bytes.fromhex("d15505")):
                headers.append(plaintext_hex)
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("fffffe")):
                headers.append(plaintext_hex)
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("fffefe")):
                trailers.append(plaintext_hex)
                continue
            if plaintext.startswith(bytes.fromhex("fefefe")):
                trailers.append(plaintext_hex)
                continue
            if plaintext.startswith(bytes.fromhex("d15507")):
                continue
            if seen_header:
                payload += plaintext
                data_frame_count += 1

    records = [
        payload[index : index + 4]
        for index in range(0, len(payload), 4)
        if len(payload[index : index + 4]) == 4 and payload[index : index + 4] != bytes(4)
    ]
    oldest_ts = active_reference_ts - timedelta(minutes=(len(records) - 1) * 2) if records else None
    return {
        "payload_bytes": len(payload),
        "non_empty_payload_bytes": len(records) * 4,
        "record_count": len(records),
        "newest_estimated_ts": reference_ts_text if records else None,
        "oldest_estimated_ts": oldest_ts.isoformat(timespec="seconds") if oldest_ts else None,
        "newest_raw": records[0].hex() if records else None,
        "oldest_raw": records[-1].hex() if records else None,
        "frame_count": frame_count,
        "data_frame_count": data_frame_count,
        "headers": headers,
        "trailers": trailers,
        "decode_error_count": decode_error_count,
    }


def _device_rssi(device: object) -> int | None:
    direct = getattr(device, "rssi", None)
    if isinstance(direct, (int, float)):
        return int(direct)
    details = getattr(device, "details", None)
    if isinstance(details, dict):
        props = details.get("props")
        if isinstance(props, dict):
            rssi = props.get("RSSI")
            if isinstance(rssi, (int, float)):
                return int(rssi)
    return None


def _bluez_client_args(adapter: str) -> BlueZClientArgs:
    active_adapter = adapter.strip()
    if not active_adapter or active_adapter == "auto":
        return {}
    return {"adapter": active_adapter}


def _bluez_scanner_args(adapter: str) -> BlueZScannerArgs:
    active_adapter = adapter.strip()
    if not active_adapter or active_adapter == "auto":
        return {}
    return {"adapter": active_adapter}


async def _drain_packets(
    queue: asyncio.Queue[bytes],
    *,
    seconds: float,
) -> list[bytes]:
    packets: list[bytes] = []
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            packets.append(await asyncio.wait_for(queue.get(), timeout=min(0.7, remaining)))
            deadline = min(deadline + 0.35, time.monotonic() + seconds)
        except TimeoutError:
            break
    return packets


class BleakProtocolProbeTransport:
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
        emit({"event": "device_start", **target.__dict__})
        device = await BleakScanner.find_device_by_address(
            target.mac,
            timeout=scan_timeout_seconds,
            bluez=_bluez_scanner_args(adapter),
        )
        if device is None:
            emit({"event": "device_not_found", **target.__dict__})
            return

        emit(
            {
                "event": "device_found",
                "id": target.id,
                "mac": target.mac,
                "name": getattr(device, "name", None),
                "rssi": _device_rssi(device),
            }
        )
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def notification_handler(_: object, data: bytearray) -> None:
            queue.put_nowait(bytes(data))

        write_response = target.family == "bm7"
        try:
            async with BleakClient(
                device,
                timeout=connect_timeout_seconds,
                bluez=_bluez_client_args(adapter),
            ) as client:
                await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
                try:
                    await asyncio.sleep(0.4)
                    passive = await _drain_packets(queue, seconds=1.0)
                    if passive:
                        emit({"event": "passive_packets", "id": target.id, "count": len(passive)})
                    for command in commands:
                        await _probe_command(
                            client=client,
                            queue=queue,
                            target=target,
                            command=command,
                            command_timeout_seconds=command_timeout_seconds,
                            write_response=write_response,
                            emit=emit,
                        )
                finally:
                    await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)
        except Exception as exc:
            emit(
                {
                    "event": "device_error",
                    "id": target.id,
                    "mac": target.mac,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc) or exc.__class__.__name__,
                }
            )


async def _probe_command(
    *,
    client: BleakClient,
    queue: asyncio.Queue[bytes],
    target: ProtocolProbeTarget,
    command: ProtocolProbeCommand,
    command_timeout_seconds: float,
    write_response: bool,
    emit: Callable[[dict[str, object]], None],
) -> None:
    emit(
        {
            "event": "command_start",
            "id": target.id,
            "command": command.name,
            "plaintext": command.plaintext.hex(),
            "write_response": write_response,
        }
    )
    try:
        await client.write_gatt_char(
            BM200_WRITE_CHARACTERISTIC,
            encrypt_probe_payload(target.family, command.plaintext),
            response=write_response,
        )
    except Exception as exc:
        emit(
            {
                "event": "command_write_error",
                "id": target.id,
                "command": command.name,
                "error_type": exc.__class__.__name__,
                "error": str(exc) or exc.__class__.__name__,
            }
        )
        await asyncio.sleep(0.6)
        return

    packets = await _drain_packets(queue, seconds=command_timeout_seconds)
    decoded: list[dict[str, object]] = []
    decoded_packets: list[DecodedProbePacket] = []
    decode_error_count = 0
    for packet in packets:
        try:
            decoded_packet = decode_probe_packet(target.family, packet)
            decoded_packets.append(decoded_packet)
            decoded.append(decoded_packet.to_dict())
        except Exception as exc:
            decode_error_count += 1
            decoded.append(
                {
                    "encrypted": packet.hex(),
                    "decrypt_error_type": exc.__class__.__name__,
                    "decrypt_error": str(exc) or exc.__class__.__name__,
                }
            )
    event: dict[str, object] = {
        "event": "command_result",
        "id": target.id,
        "command": command.name,
        "plaintext": command.plaintext.hex(),
        "packet_count": len(packets),
        "packets": decoded,
    }
    if command.plaintext.startswith(bytes.fromhex("d15505")):
        event["history_summary"] = summarize_d15505_probe_packets(
            target.family,
            decoded_packets,
            reference_ts=datetime.now().astimezone().replace(microsecond=0),
            decode_error_count=decode_error_count,
        )
    emit(event)
    await asyncio.sleep(0.7)


async def run_protocol_probe(
    *,
    devices: Sequence[Device],
    device_ids: Sequence[str],
    adapter: str,
    scan_timeout_seconds: float,
    connect_timeout_seconds: float,
    command_timeout_seconds: float = 3.5,
    history_page_limit: int = 1,
    commands: Sequence[ProtocolProbeCommand] | None = None,
    transport: ProtocolProbeTransport | None = None,
    emit: Callable[[dict[str, object]], None],
) -> None:
    selected_ids = set(device_ids)
    selected_devices = [
        device
        for device in devices
        if device.enabled and (not selected_ids or device.id in selected_ids)
    ]
    active_transport = transport or BleakProtocolProbeTransport()
    active_commands = (
        tuple(commands)
        if commands is not None
        else build_probe_commands(history_page_limit=history_page_limit)
    )
    emit(
        {
            "event": "probe_start",
            "device_count": len(selected_devices),
            "command_count": len(active_commands),
        }
    )
    for device in selected_devices:
        target = target_for_device(device)
        if target.family not in {"bm6", "bm7"}:
            emit({"event": "device_skipped", **target.__dict__, "reason": "unsupported_family"})
            continue
        await active_transport.probe(
            target=target,
            commands=active_commands,
            adapter=adapter,
            scan_timeout_seconds=scan_timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
            command_timeout_seconds=command_timeout_seconds,
            emit=emit,
        )
        await asyncio.sleep(1.5)
    emit({"event": "probe_end"})
