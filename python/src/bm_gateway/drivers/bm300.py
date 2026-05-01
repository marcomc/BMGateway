"""BM300 Pro / BM7 Bluetooth protocol support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from bleak import BleakClient, BleakScanner
from bleak.args.bluez import BlueZClientArgs, BlueZScannerArgs
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


@dataclass(frozen=True)
class BM300HistoryReading:
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


class BM300HistoryTransport(Protocol):
    async def read_history(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        page_count: int = 1,
    ) -> list[BM300HistoryReading]: ...


class BM300HistoryRequestTransport(Protocol):
    async def read_history_request(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        request: bytes,
        page_selector: int,
    ) -> list[BM300HistoryReading]: ...


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


def _create_cipher() -> Any:
    return AES.new(BM300_AES_KEY, AES.MODE_CBC, bytes(BM300_BLOCK_SIZE))


def _pad_payload(data: bytes) -> bytes:
    size = ((len(data) + BM300_BLOCK_SIZE - 1) // BM300_BLOCK_SIZE) * BM300_BLOCK_SIZE
    return data.ljust(size, b"\x00")


def encrypt_bm300_payload(plaintext: bytes) -> bytes:
    return bytes(_create_cipher().encrypt(_pad_payload(plaintext)))


def decrypt_bm300_payload(encrypted: bytes | bytearray) -> bytes:
    return bytes(_create_cipher().decrypt(bytes(encrypted)))


def decode_bm300_frame_payloads(encrypted: bytes | bytearray) -> list[bytes]:
    encrypted_bytes = bytes(encrypted)
    if len(encrypted_bytes) % BM300_BLOCK_SIZE != 0:
        raise BM300ProtocolError("BM300 Pro encrypted payload is not block aligned")
    return [
        decrypt_bm300_payload(encrypted_bytes[index : index + BM300_BLOCK_SIZE])
        for index in range(0, len(encrypted_bytes), BM300_BLOCK_SIZE)
    ]


def encode_bm7_history_request(page_count: int) -> bytes:
    if page_count < 1 or page_count > 255:
        raise ValueError("page_count must be between 1 and 255")
    return encode_bm7_history_request_for_byte(byte_index=6, selector_value=page_count)


def encode_bm7_history_request_for_byte(*, byte_index: int, selector_value: int) -> bytes:
    if byte_index < 0 or byte_index > 15:
        raise ValueError("byte_index must be between 0 and 15")
    if selector_value < 1 or selector_value > 255:
        raise ValueError("selector_value must be between 1 and 255")
    request = bytearray(16)
    request[0:3] = bytes([0xD1, 0x55, 0x05])
    request[byte_index] = selector_value
    return bytes(request)


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


def parse_bm7_history_items(
    payload: bytes,
    *,
    reference_ts: datetime,
    page_selector: int,
    timestamp_quality: str = "estimated",
) -> list[BM300HistoryReading]:
    items = [
        payload[index : index + 4]
        for index in range(0, len(payload), 4)
        if len(payload[index : index + 4]) == 4 and payload[index : index + 4] != bytes(4)
    ]
    readings: list[BM300HistoryReading] = []
    for index, item in enumerate(items):
        raw = item.hex()
        ts = reference_ts - timedelta(minutes=index * 2)
        readings.append(
            BM300HistoryReading(
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


def default_bm7_history_reference_ts(now: datetime | None = None) -> datetime:
    active_now = now or datetime.now().astimezone()
    if active_now.tzinfo is None:
        active_now = active_now.astimezone()
    reference_ts = active_now.replace(second=0, microsecond=0)
    return reference_ts - timedelta(minutes=reference_ts.minute % 2)


async def read_bm300_history_selector(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    selector_byte: int,
    selector_value: int,
    reference_ts: datetime | None = None,
    transport: BM300HistoryRequestTransport | None = None,
) -> list[BM300HistoryReading]:
    active_transport = transport or BleakBM7HistoryTransport()
    return await active_transport.read_history_request(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        scan_timeout_seconds=scan_timeout_seconds,
        reference_ts=reference_ts or default_bm7_history_reference_ts(),
        request=encode_bm7_history_request_for_byte(
            byte_index=selector_byte,
            selector_value=selector_value,
        ),
        page_selector=selector_value,
    )


def _is_bm300_measurement_packet(encrypted: bytes) -> bool:
    try:
        plaintext = decrypt_bm300_payload(encrypted)
        parse_bm300_plaintext_measurement(plaintext)
    except (ValueError, BM300ProtocolError):
        return False
    return True


class BleakBM300Transport:
    async def _read_voltage_notification_attempt(
        self,
        *,
        client: BleakClient,
        deadline: float,
    ) -> bytes:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def notification_handler(
            _: object,
            data: bytearray,
            *,
            notification_queue: asyncio.Queue[bytes] = queue,
        ) -> None:
            notification_queue.put_nowait(bytes(data))

        async with client:
            await client.start_notify(BM300_NOTIFY_CHARACTERISTIC, notification_handler)
            try:
                request_attempts = 0
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise BM300TimeoutError(str(getattr(client, "address", "bm300")))
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
                            raise BM300TimeoutError(
                                str(getattr(client, "address", "bm300"))
                            ) from exc
                        continue
                    if _is_bm300_measurement_packet(encrypted):
                        return encrypted
            finally:
                await client.stop_notify(BM300_NOTIFY_CHARACTERISTIC)

    async def read_voltage_notification(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
    ) -> tuple[bytes, int | None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_error: Exception | None = None
        scan_timeout = max(1.0, scan_timeout_seconds)
        bluez_scanner_args = _bluez_scanner_args(adapter)
        bluez_client_args = _bluez_client_args(adapter)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise BleakBM300DeviceNotFoundError(address)

            device = await BleakScanner.find_device_by_address(
                address,
                timeout=min(scan_timeout, remaining),
                bluez=bluez_scanner_args,
            )
            if device is None:
                continue
            rssi = _device_rssi(device)

            client = BleakClient(
                device,
                timeout=min(scan_timeout, remaining),
                bluez=bluez_client_args,
            )
            try:
                encrypted = await asyncio.wait_for(
                    self._read_voltage_notification_attempt(
                        client=client,
                        deadline=deadline,
                    ),
                    timeout=max(deadline - loop.time(), 0.0),
                )
                return encrypted, rssi
            except TimeoutError as exc:
                last_error = BM300TimeoutError(address)
                if deadline - loop.time() <= 0:
                    raise last_error from exc
            except BM300TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue


class BleakBM7HistoryTransport:
    async def _read_history_request_attempt(
        self,
        *,
        client: BleakClient,
        deadline: float,
        reference_ts: datetime,
        request: bytes,
        page_selector: int,
    ) -> list[BM300HistoryReading]:
        packet_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def notification_handler(
            _: object,
            data: bytearray,
            *,
            notification_queue: asyncio.Queue[bytes] = packet_queue,
        ) -> None:
            notification_queue.put_nowait(bytes(data))

        async with client:
            await client.start_notify(BM300_NOTIFY_CHARACTERISTIC, notification_handler)
            try:
                await asyncio.sleep(
                    min(0.4, max(deadline - asyncio.get_running_loop().time(), 0.0))
                )
                await client.write_gatt_char(
                    BM300_WRITE_CHARACTERISTIC,
                    encrypt_bm300_payload(BM300_POLL_PLAINTEXT),
                    response=True,
                )
                await _drain_bm7_wake_packets(packet_queue, deadline=deadline)
                await client.write_gatt_char(
                    BM300_WRITE_CHARACTERISTIC,
                    encrypt_bm300_payload(request),
                    response=True,
                )
                payload = await _collect_bm7_history_payload(
                    packet_queue,
                    deadline=deadline,
                )
                return parse_bm7_history_items(
                    payload,
                    reference_ts=reference_ts,
                    page_selector=page_selector,
                )
            finally:
                await client.stop_notify(BM300_NOTIFY_CHARACTERISTIC)

    async def read_history_request(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        request: bytes,
        page_selector: int,
    ) -> list[BM300HistoryReading]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_error: Exception | None = None
        scan_timeout = max(1.0, scan_timeout_seconds)
        bluez_scanner_args = _bluez_scanner_args(adapter)
        bluez_client_args = _bluez_client_args(adapter)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise BleakBM300DeviceNotFoundError(address)

            device = await BleakScanner.find_device_by_address(
                address,
                timeout=min(scan_timeout, remaining),
                bluez=bluez_scanner_args,
            )
            if device is None:
                continue

            client = BleakClient(
                device,
                timeout=min(scan_timeout, remaining),
                bluez=bluez_client_args,
            )

            try:
                return await asyncio.wait_for(
                    self._read_history_request_attempt(
                        client=client,
                        deadline=deadline,
                        reference_ts=reference_ts,
                        request=request,
                        page_selector=page_selector,
                    ),
                    timeout=max(deadline - loop.time(), 0.0),
                )
            except TimeoutError as exc:
                last_error = BM300TimeoutError(address)
                if deadline - loop.time() <= 0:
                    raise last_error from exc
            except BM300TimeoutError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(deadline - loop.time(), 0.0)))
                continue

    async def read_history(
        self,
        *,
        address: str,
        adapter: str,
        timeout_seconds: float,
        scan_timeout_seconds: float,
        reference_ts: datetime,
        page_count: int = 1,
    ) -> list[BM300HistoryReading]:
        return await self.read_history_request(
            address=address,
            adapter=adapter,
            timeout_seconds=timeout_seconds,
            scan_timeout_seconds=scan_timeout_seconds,
            reference_ts=reference_ts,
            request=encode_bm7_history_request(page_count),
            page_selector=page_count,
        )


async def _collect_bm7_history_payload(
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
            raise BM300TimeoutError("bm7 history")
        try:
            encrypted = await asyncio.wait_for(
                packet_queue.get(),
                timeout=min(idle_timeout_seconds, remaining),
            )
        except TimeoutError:
            if payload:
                return payload
            continue
        for plaintext in decode_bm300_frame_payloads(encrypted):
            if plaintext.startswith(bytes.fromhex("d15505")):
                seen_header = True
                continue
            if plaintext.startswith(bytes.fromhex("d15507")):
                continue
            if plaintext.startswith(bytes.fromhex("fffffe")):
                seen_header = True
                continue
            if seen_header:
                trailer_offset = _history_trailer_offset(plaintext)
                if trailer_offset is not None:
                    payload += plaintext[:trailer_offset]
                    return payload
                payload += plaintext


def _history_trailer_offset(plaintext: bytes) -> int | None:
    offsets = [
        offset
        for marker in (bytes.fromhex("fffefe"), bytes.fromhex("fefefe"))
        for offset in [plaintext.find(marker)]
        if offset >= 0
    ]
    if not offsets:
        return None
    return min(offsets)


async def _drain_bm7_wake_packets(
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


async def read_bm300_history(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    scan_timeout_seconds: float,
    page_count: int = 1,
    reference_ts: datetime | None = None,
    transport: BM300HistoryTransport | None = None,
) -> list[BM300HistoryReading]:
    active_transport = transport or BleakBM7HistoryTransport()
    return await active_transport.read_history(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        scan_timeout_seconds=scan_timeout_seconds,
        reference_ts=reference_ts or default_bm7_history_reference_ts(),
        page_count=page_count,
    )
