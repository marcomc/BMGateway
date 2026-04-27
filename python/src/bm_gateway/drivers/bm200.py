"""BM200 Bluetooth protocol support."""

from __future__ import annotations

import asyncio
import binascii
import itertools
import struct
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from bleak import BleakClient, BleakScanner
from Crypto.Cipher import AES

BM200_NOTIFY_CHARACTERISTIC = "0000fff4-0000-1000-8000-00805f9b34fb"
BM200_WRITE_CHARACTERISTIC = "0000fff3-0000-1000-8000-00805f9b34fb"
BM200_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 49, 56, 56, 50, 52, 54, 54])
BM6_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 48, 49, 48, 48, 48, 48, 57])
BM200_BLOCK_SIZE = 16
BM6_POLL_PLAINTEXT = bytes.fromhex("d1550700000000000000000000000000")
BM200_STATUS = {
    0: "critical",
    1: "low",
    2: "normal",
    4: "charging",
    8: "floating",
}
BM6_STATUS = {
    0: "normal",
    1: "low",
    2: "charging",
}


@dataclass(frozen=True)
class BM200Measurement:
    voltage: float
    soc: int
    status_code: int
    state: str
    temperature: float | None = None
    rssi: int | None = None


@dataclass(frozen=True)
class BM200HistoryReading:
    ts: str
    voltage: float
    min_crank_voltage: float | None
    event_type: int | None
    soc: int | None = None
    temperature: float | None = None
    raw_record: str | None = None
    page_selector: int | None = None
    record_index: int | None = None
    timestamp_quality: str = "estimated"


class BM200Error(Exception):
    """Base error for BM200 driver failures."""


class BM200TimeoutError(BM200Error):
    """Raised when no voltage notification is received in time."""


class BM200ProtocolError(BM200Error):
    """Raised when the payload is not a BM200 voltage packet."""


class BM200Transport(Protocol):
    async def read_voltage_notification(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> tuple[bytes, int | None]: ...


class BM200HistoryTransport(Protocol):
    async def read_history(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        page_count: int = 1,
    ) -> list[BM200HistoryReading]: ...


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
    return _create_cipher_for_key(BM200_AES_KEY)


def _create_cipher_for_key(key: bytes) -> Any:
    return AES.new(key, AES.MODE_CBC, bytes(BM200_BLOCK_SIZE))


def _pad_payload(data: bytes) -> bytes:
    size = ((len(data) + BM200_BLOCK_SIZE - 1) // BM200_BLOCK_SIZE) * BM200_BLOCK_SIZE
    return data.ljust(size, b"\x00")


def encrypt_payload(plaintext: bytes) -> bytes:
    return bytes(_create_cipher().encrypt(_pad_payload(plaintext)))


def encrypt_bm6_payload(plaintext: bytes) -> bytes:
    return bytes(_create_cipher_for_key(BM6_AES_KEY).encrypt(_pad_payload(plaintext)))


def decrypt_payload(encrypted: bytes | bytearray) -> bytes:
    return bytes(_create_cipher().decrypt(bytes(encrypted)))


def decrypt_bm6_payload(encrypted: bytes | bytearray) -> bytes:
    return bytes(_create_cipher_for_key(BM6_AES_KEY).decrypt(bytes(encrypted)))


def decode_bm6_frame_payloads(encrypted: bytes | bytearray) -> list[bytes]:
    encrypted_bytes = bytes(encrypted)
    if len(encrypted_bytes) % BM200_BLOCK_SIZE != 0:
        raise BM200ProtocolError("BM6 encrypted payload is not block aligned")
    return [
        decrypt_bm6_payload(encrypted_bytes[index : index + BM200_BLOCK_SIZE])
        for index in range(0, len(encrypted_bytes), BM200_BLOCK_SIZE)
    ]


def parse_plaintext_measurement(plaintext: bytes) -> BM200Measurement:
    if len(plaintext) < 4 or plaintext[0] != 0xF5:
        raise BM200ProtocolError("plaintext does not contain a BM200 voltage packet")

    raw = plaintext.hex()
    voltage = int(raw[2:5], 16) / 100.0
    status_code = int(raw[5:6], 16)
    soc = int(raw[6:8], 16)
    return BM200Measurement(
        voltage=voltage,
        soc=soc,
        temperature=None,
        status_code=status_code,
        state=BM200_STATUS.get(status_code, "unknown"),
    )


def parse_bm6_plaintext_measurement(plaintext: bytes) -> BM200Measurement:
    if len(plaintext) < 16 or not plaintext.startswith(bytes.fromhex("d15507")):
        raise BM200ProtocolError("plaintext does not contain a BM6 voltage packet")
    if plaintext[3] == 0xFF:
        raise BM200ProtocolError("plaintext contains a BM6 acknowledgement packet")

    raw = plaintext.hex()
    voltage = int(raw[15:18], 16) / 100.0
    soc = int(raw[12:14], 16)
    status_code = plaintext[5]
    temperature_raw = plaintext[4]
    temperature = -float(temperature_raw) if plaintext[3] == 0x01 else float(temperature_raw)
    return BM200Measurement(
        voltage=voltage,
        soc=soc,
        temperature=temperature,
        status_code=status_code,
        state=BM6_STATUS.get(status_code, "unknown"),
    )


def parse_voltage_notification(encrypted: bytes | bytearray) -> BM200Measurement:
    errors: list[Exception] = []
    for decryptor, parser in (
        (decrypt_payload, parse_plaintext_measurement),
        (decrypt_bm6_payload, parse_bm6_plaintext_measurement),
    ):
        try:
            return parser(decryptor(encrypted))
        except BM200ProtocolError as exc:
            errors.append(exc)
    raise BM200ProtocolError(str(errors[-1]))


def encode_history_count_request() -> bytes:
    return bytes([0xE7, 0x01])


def encode_history_download_request(size: int) -> bytes:
    return bytes([0xE3, 0x00, 0x00, *struct.pack(">L", size)])


def encode_bm6_history_request(page_count: int) -> bytes:
    if page_count < 1 or page_count > 255:
        raise ValueError("page_count must be between 1 and 255")
    return bytes([0xD1, 0x55, 0x05, 0, 0, 0, 0, page_count, 0, 0, 0, 0, 0, 0, 0, 0])


def decode_history_count_packet(plaintext: bytes) -> int:
    if len(plaintext) < 4 or plaintext[0] != 0xE7:
        raise BM200ProtocolError("plaintext does not contain a BM200 history-count packet")
    return int(struct.unpack(">L", bytes([0, *plaintext[1:4]]))[0])


def decode_3bytes(payload: bytes) -> int:
    return int(struct.unpack(">L", bytes([0, *payload[:3]]))[0])


def decode_history_nibbles(payload: bytes, fmt: str) -> list[int]:
    hex_str = binascii.hexlify(payload)
    letter_groups = [(item[0], len(list(item[1]))) for item in itertools.groupby(fmt)]
    index = 0
    values: list[int] = []
    for _letter, letters_count in letter_groups:
        part = hex_str[index : index + letters_count]
        index += letters_count
        values.append(
            sum(int(chr(value), 16) << (4 * bit) for bit, value in enumerate(reversed(part)))
        )
    return values


def parse_history_items(
    payload: bytes,
    *,
    reference_ts: datetime,
) -> list[BM200HistoryReading]:
    items = [
        payload[index : index + 4]
        for index in range(0, len(payload), 4)
        if len(payload[index : index + 4]) == 4
    ]
    total_items = len(items)
    readings: list[BM200HistoryReading] = []
    for index, item in enumerate(items):
        values = decode_history_nibbles(item, "xxxkyyyp")
        ts = reference_ts - timedelta(minutes=(total_items - 1 - index) * 2)
        readings.append(
            BM200HistoryReading(
                ts=ts.isoformat(timespec="seconds"),
                voltage=values[0] / 100,
                min_crank_voltage=values[2] / 100,
                event_type=values[3],
            )
        )
    return readings


def parse_bm6_history_items(
    payload: bytes,
    *,
    reference_ts: datetime,
    page_selector: int,
    timestamp_quality: str = "estimated",
) -> list[BM200HistoryReading]:
    items = [
        payload[index : index + 4]
        for index in range(0, len(payload), 4)
        if len(payload[index : index + 4]) == 4 and payload[index : index + 4] != bytes(4)
    ]
    readings: list[BM200HistoryReading] = []
    for index, item in enumerate(items):
        raw = item.hex()
        ts = reference_ts - timedelta(minutes=index * 2)
        readings.append(
            BM200HistoryReading(
                ts=ts.isoformat(timespec="seconds"),
                voltage=int(raw[0:3], 16) / 100,
                min_crank_voltage=None,
                event_type=int(raw[7], 16),
                soc=int(raw[3:5], 16),
                temperature=float(int(raw[5:7], 16)),
                raw_record=raw,
                page_selector=page_selector,
                record_index=index,
                timestamp_quality=timestamp_quality,
            )
        )
    return readings


def default_bm6_history_reference_ts(now: datetime | None = None) -> datetime:
    active_now = now or datetime.now().astimezone()
    if active_now.tzinfo is None:
        active_now = active_now.astimezone()
    reference_ts = active_now.replace(second=0, microsecond=0)
    return reference_ts - timedelta(minutes=reference_ts.minute % 2)


class BleakBM200Transport:
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
                raise BleakDeviceNotFoundError(address)

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
                    await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
                    try:
                        # BM6-family devices do not reliably stream passive
                        # notifications. Arm notify first, then issue the poll
                        # request immediately and retry once before giving up
                        # on this connection window.
                        request_attempts = 0
                        while True:
                            remaining = deadline - loop.time()
                            if remaining <= 0:
                                raise BM200TimeoutError(address)
                            try:
                                if request_attempts == 0:
                                    await asyncio.sleep(min(0.5, remaining))
                                await client.write_gatt_char(
                                    BM200_WRITE_CHARACTERISTIC,
                                    encrypt_bm6_payload(BM6_POLL_PLAINTEXT),
                                    response=False,
                                )
                                request_attempts += 1
                                encrypted = await asyncio.wait_for(
                                    queue.get(),
                                    timeout=min(4.0, remaining),
                                )
                            except TimeoutError as exc:
                                if request_attempts >= 2:
                                    raise BM200TimeoutError(address) from exc
                                continue
                            if _is_bm200_measurement_packet(
                                encrypted
                            ) or _is_bm6_measurement_packet(encrypted):
                                return encrypted, rssi
                    finally:
                        await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)
            except BM200TimeoutError:
                raise
            except Exception as exc:
                # The device was seen but failed to connect cleanly in this
                # window. Retry discovery until the overall deadline expires.
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue


class BleakBM200HistoryTransport:
    async def read_history(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        page_count: int = 1,
    ) -> list[BM200HistoryReading]:
        _ = (adapter, page_count)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_error: Exception | None = None
        scan_timeout = max(1.0, scan_timeout_seconds)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise BleakDeviceNotFoundError(address)

            device = await BleakScanner.find_device_by_address(
                address,
                timeout=min(scan_timeout, remaining),
            )
            if device is None:
                continue

            client = BleakClient(device, timeout=min(scan_timeout, remaining))
            packet_queue: asyncio.Queue[bytes] = asyncio.Queue()

            def notification_handler(
                _: object,
                data: bytearray,
                *,
                notification_queue: asyncio.Queue[bytes] = packet_queue,
            ) -> None:
                notification_queue.put_nowait(bytes(data))

            try:
                async with client:
                    await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
                    try:
                        await client.write_gatt_char(
                            BM200_WRITE_CHARACTERISTIC,
                            encrypt_payload(encode_history_count_request()),
                            response=False,
                        )
                        history_size = await _await_history_size(
                            packet_queue,
                            deadline=deadline,
                        )
                        if history_size == 0:
                            return []
                        await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                        await client.write_gatt_char(
                            BM200_WRITE_CHARACTERISTIC,
                            encrypt_payload(encode_history_download_request(history_size)),
                            response=False,
                        )
                        payload = await _collect_history_payload(
                            packet_queue,
                            deadline=deadline,
                        )
                        return parse_history_items(payload, reference_ts=reference_ts)
                    finally:
                        await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)
            except BM200TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue


class BleakBM6HistoryTransport:
    async def read_history(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        page_count: int = 1,
    ) -> list[BM200HistoryReading]:
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
                raise BleakDeviceNotFoundError(address)

            device = await BleakScanner.find_device_by_address(
                address,
                timeout=min(scan_timeout, remaining),
            )
            if device is None:
                continue

            client = BleakClient(device, timeout=min(scan_timeout, remaining))
            packet_queue: asyncio.Queue[bytes] = asyncio.Queue()

            def notification_handler(
                _: object,
                data: bytearray,
                *,
                notification_queue: asyncio.Queue[bytes] = packet_queue,
            ) -> None:
                notification_queue.put_nowait(bytes(data))

            try:
                async with client:
                    await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
                    try:
                        await asyncio.sleep(min(0.4, max(deadline - loop.time(), 0.0)))
                        await client.write_gatt_char(
                            BM200_WRITE_CHARACTERISTIC,
                            encrypt_bm6_payload(BM6_POLL_PLAINTEXT),
                            response=False,
                        )
                        await _drain_bm6_wake_packets(packet_queue, deadline=deadline)
                        await client.write_gatt_char(
                            BM200_WRITE_CHARACTERISTIC,
                            encrypt_bm6_payload(encode_bm6_history_request(page_count)),
                            response=False,
                        )
                        payload = await _collect_bm6_history_payload(
                            packet_queue,
                            deadline=deadline,
                        )
                        return parse_bm6_history_items(
                            payload,
                            reference_ts=reference_ts,
                            page_selector=page_count,
                        )
                    finally:
                        await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)
            except BM200TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue


def _is_bm200_measurement_packet(encrypted: bytes) -> bool:
    try:
        plaintext = decrypt_payload(encrypted)
    except ValueError:
        return False
    return bool(plaintext) and plaintext[0] == 0xF5


def _is_bm6_measurement_packet(encrypted: bytes) -> bool:
    try:
        plaintext = decrypt_bm6_payload(encrypted)
    except ValueError:
        return False
    return (
        len(plaintext) >= 16
        and plaintext.startswith(bytes.fromhex("d15507"))
        and plaintext[3] != 0xFF
    )


class BleakDeviceNotFoundError(BM200Error):
    """Raised when a scanned device cannot be resolved before connecting."""


async def _next_decrypted_packet(packet_queue: asyncio.Queue[bytes], *, deadline: float) -> bytes:
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    if remaining <= 0:
        raise BM200TimeoutError("history")
    encrypted = await asyncio.wait_for(packet_queue.get(), timeout=min(4.0, remaining))
    try:
        return decrypt_payload(encrypted)
    except ValueError as exc:  # pragma: no cover - defensive
        raise BM200ProtocolError("failed to decrypt history packet") from exc


async def _await_history_size(packet_queue: asyncio.Queue[bytes], *, deadline: float) -> int:
    while True:
        plaintext = await _next_decrypted_packet(packet_queue, deadline=deadline)
        if len(plaintext) >= 4 and plaintext[0] == 0xE7:
            return decode_history_count_packet(plaintext)


async def _collect_history_payload(packet_queue: asyncio.Queue[bytes], *, deadline: float) -> bytes:
    receiving = False
    history_data = b""
    while True:
        plaintext = await _next_decrypted_packet(packet_queue, deadline=deadline)
        if plaintext.startswith(bytes.fromhex("fffffe")):
            receiving = True
            history_data = b""
            continue
        if not receiving:
            continue
        if plaintext.startswith(bytes.fromhex("fffefe")):
            history_size = decode_3bytes(plaintext[3:6]) - 9
            return history_data[:history_size]
        history_data += plaintext


async def _collect_bm6_history_payload(
    packet_queue: asyncio.Queue[bytes],
    *,
    deadline: float,
) -> bytes:
    loop = asyncio.get_running_loop()
    payload = b""
    seen_header = False
    idle_timeout_seconds = 3.0
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            if payload:
                return payload
            raise BM200TimeoutError("bm6 history")
        try:
            encrypted = await asyncio.wait_for(
                packet_queue.get(),
                timeout=min(idle_timeout_seconds, remaining),
            )
        except TimeoutError:
            if payload:
                return payload
            continue
        for plaintext in decode_bm6_frame_payloads(encrypted):
            if plaintext.startswith(bytes.fromhex("d15505")):
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("d15507")):
                continue
            if plaintext.startswith(bytes.fromhex("fffffe")):
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("fffefe")):
                return payload
            if seen_header:
                payload += plaintext


async def _drain_bm6_wake_packets(
    packet_queue: asyncio.Queue[bytes],
    *,
    deadline: float,
) -> None:
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(packet_queue.get(), timeout=min(0.3, remaining))
        except TimeoutError:
            return


async def read_bm200_measurement(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    transport: BM200Transport | None = None,
) -> BM200Measurement:
    active_transport = transport or BleakBM200Transport()
    encrypted, rssi = await active_transport.read_voltage_notification(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        scan_timeout_seconds=scan_timeout_seconds,
    )
    measurement = parse_voltage_notification(encrypted)
    if rssi is None:
        return measurement
    return replace(measurement, rssi=rssi)


async def read_bm200_history(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    page_count: int = 1,
    reference_ts: datetime | None = None,
    transport: BM200HistoryTransport | None = None,
) -> list[BM200HistoryReading]:
    active_transport = transport or BleakBM6HistoryTransport()
    return await active_transport.read_history(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        scan_timeout_seconds=scan_timeout_seconds,
        reference_ts=reference_ts or default_bm6_history_reference_ts(),
        page_count=page_count,
    )
