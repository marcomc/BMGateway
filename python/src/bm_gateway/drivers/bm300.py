"""BM300 Pro / BM7 Bluetooth protocol support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Protocol

from bleak import BleakClient, BleakScanner
from Crypto.Cipher import AES

BM300_NOTIFY_CHARACTERISTIC = "0000fff4-0000-1000-8000-00805f9b34fb"
BM300_WRITE_CHARACTERISTIC = "0000fff3-0000-1000-8000-00805f9b34fb"
BM300_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 48, 49, 48, 48, 48, 48, 64])
BM300_BLOCK_SIZE = 16
BM300_POLL_PLAINTEXT = bytes.fromhex("d1550700000000000000000000000000")
BM300_STATUS = {
    0: "normal",
    1: "low",
    2: "charging",
}


@dataclass(frozen=True)
class BM300Measurement:
    voltage: float
    soc: int
    status_code: int
    state: str
    temperature: float | None = None
    rssi: int | None = None


class BM300Error(Exception):
    """Base error for BM300 Pro driver failures."""


class BM300TimeoutError(BM300Error):
    """Raised when no voltage notification is received in time."""


class BM300ProtocolError(BM300Error):
    """Raised when the payload is not a BM300 Pro voltage packet."""


class BleakBM300DeviceNotFoundError(BM300Error):
    """Raised when a scanned device cannot be resolved before connecting."""


class BM300Transport(Protocol):
    async def read_voltage_notification(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> tuple[bytes, int | None]: ...


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


def _create_cipher() -> Any:
    return AES.new(BM300_AES_KEY, AES.MODE_CBC, bytes(BM300_BLOCK_SIZE))


def _pad_payload(data: bytes) -> bytes:
    size = ((len(data) + BM300_BLOCK_SIZE - 1) // BM300_BLOCK_SIZE) * BM300_BLOCK_SIZE
    return data.ljust(size, b"\x00")


def encrypt_bm300_payload(plaintext: bytes) -> bytes:
    return bytes(_create_cipher().encrypt(_pad_payload(plaintext)))


def decrypt_bm300_payload(encrypted: bytes | bytearray) -> bytes:
    return bytes(_create_cipher().decrypt(bytes(encrypted)))


def parse_bm300_plaintext_measurement(plaintext: bytes) -> BM300Measurement:
    if len(plaintext) < 16 or not plaintext.startswith(bytes.fromhex("d15507")):
        raise BM300ProtocolError("plaintext does not contain a BM300 Pro voltage packet")
    if plaintext[3] == 0xFF:
        raise BM300ProtocolError("plaintext contains a BM300 Pro acknowledgement packet")

    status_code = plaintext[5]
    temperature_raw = plaintext[4]
    temperature = -float(temperature_raw) if plaintext[3] == 0x01 else float(temperature_raw)
    voltage = ((plaintext[7] << 8) | plaintext[8]) / 100.0
    return BM300Measurement(
        voltage=voltage,
        soc=plaintext[6],
        temperature=temperature,
        status_code=status_code,
        state=BM300_STATUS.get(status_code, "unknown"),
    )


def parse_bm300_voltage_notification(encrypted: bytes | bytearray) -> BM300Measurement:
    try:
        plaintext = decrypt_bm300_payload(encrypted)
    except ValueError as exc:
        raise BM300ProtocolError("failed to decrypt BM300 Pro packet") from exc
    return parse_bm300_plaintext_measurement(plaintext)


def _is_bm300_measurement_packet(encrypted: bytes) -> bool:
    try:
        plaintext = decrypt_bm300_payload(encrypted)
        parse_bm300_plaintext_measurement(plaintext)
    except (ValueError, BM300ProtocolError):
        return False
    return True


class BleakBM300Transport:
    async def read_voltage_notification(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> tuple[bytes, int | None]:
        _ = adapter
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_error: Exception | None = None
        scan_timeout = max(1.0, scan_timeout_seconds)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise BleakBM300DeviceNotFoundError(address)

            queue: asyncio.Queue[bytes] = asyncio.Queue()

            def notification_handler(
                _: object,
                data: bytearray,
                *,
                notification_queue: asyncio.Queue[bytes] = queue,
            ) -> None:
                notification_queue.put_nowait(bytes(data))

            device = await BleakScanner.find_device_by_address(
                address,
                timeout=min(scan_timeout, remaining),
            )
            if device is None:
                continue
            rssi = _device_rssi(device)

            client = BleakClient(device, timeout=min(scan_timeout, remaining))
            try:
                async with client:
                    await client.start_notify(BM300_NOTIFY_CHARACTERISTIC, notification_handler)
                    try:
                        request_attempts = 0
                        while True:
                            remaining = deadline - loop.time()
                            if remaining <= 0:
                                raise BM300TimeoutError(address)
                            try:
                                if request_attempts == 0:
                                    await asyncio.sleep(min(0.5, remaining))
                                await client.write_gatt_char(
                                    BM300_WRITE_CHARACTERISTIC,
                                    encrypt_bm300_payload(BM300_POLL_PLAINTEXT),
                                    response=True,
                                )
                                request_attempts += 1
                                encrypted = await asyncio.wait_for(
                                    queue.get(),
                                    timeout=min(4.0, remaining),
                                )
                            except TimeoutError as exc:
                                if request_attempts >= 2:
                                    raise BM300TimeoutError(address) from exc
                                continue
                            if _is_bm300_measurement_packet(encrypted):
                                return encrypted, rssi
                    finally:
                        await client.stop_notify(BM300_NOTIFY_CHARACTERISTIC)
            except BM300TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue


async def read_bm300_measurement(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    transport: BM300Transport | None = None,
) -> BM300Measurement:
    active_transport = transport or BleakBM300Transport()
    encrypted, rssi = await active_transport.read_voltage_notification(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        scan_timeout_seconds=scan_timeout_seconds,
    )
    measurement = parse_bm300_voltage_notification(encrypted)
    if rssi is None:
        return measurement
    return replace(measurement, rssi=rssi)
