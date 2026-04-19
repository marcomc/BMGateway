"""BM200 Bluetooth protocol support."""

from __future__ import annotations

import asyncio
import binascii
import itertools
import struct
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BM200Measurement:
    voltage: float
    soc: int
    status_code: int
    state: str


@dataclass(frozen=True)
class BM200HistoryReading:
    ts: str
    voltage: float
    min_crank_voltage: float
    event_type: int


class BM200Error(Exception):
    """Base error for BM200 driver failures."""


class BM200TimeoutError(BM200Error):
    """Raised when no voltage notification is received in time."""


class BM200ProtocolError(BM200Error):
    """Raised when the payload is not a BM200 voltage packet."""


class BM200Transport(Protocol):
    async def read_voltage_notification(
        self, *, address: str, adapter: str, timeout_seconds: float
    ) -> bytes: ...


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
    return BM200Measurement(
        voltage=voltage,
        soc=soc,
        status_code=2,
        state="normal",
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


def decode_history_count_packet(plaintext: bytes) -> int:
    if len(plaintext) < 4 or plaintext[0] != 0xE7:
        raise BM200ProtocolError("plaintext does not contain a BM200 history-count packet")
    return int(struct.unpack(">L", bytes([0, *plaintext[1:4]]))[0])


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


class BleakBM200Transport:
    async def read_voltage_notification(
        self, *, address: str, adapter: str, timeout_seconds: float
    ) -> bytes:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
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
                timeout=min(4.0, remaining),
            )
            if device is None:
                continue

            client = BleakClient(device, timeout=min(10.0, remaining))
            try:
                async with client:
                    await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
                    try:
                        bm6_request_sent = False
                        while True:
                            remaining = deadline - loop.time()
                            if remaining <= 0:
                                raise BM200TimeoutError(address)
                            try:
                                encrypted = await asyncio.wait_for(
                                    queue.get(),
                                    timeout=min(2.0, remaining),
                                )
                            except TimeoutError as exc:
                                if bm6_request_sent:
                                    raise BM200TimeoutError(address) from exc
                                await client.write_gatt_char(
                                    BM200_WRITE_CHARACTERISTIC,
                                    encrypt_bm6_payload(BM6_POLL_PLAINTEXT),
                                    response=False,
                                )
                                bm6_request_sent = True
                                continue
                            if _is_bm200_measurement_packet(
                                encrypted
                            ) or _is_bm6_measurement_packet(encrypted):
                                return encrypted
                    finally:
                        await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)
            except BM200TimeoutError:
                raise
            except Exception:
                # The device was seen but failed to connect cleanly in this
                # window. Retry discovery until the overall deadline expires.
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


async def read_bm200_measurement(
    *,
    address: str,
    adapter: str,
    timeout_seconds: float,
    transport: BM200Transport | None = None,
) -> BM200Measurement:
    active_transport = transport or BleakBM200Transport()
    encrypted = await active_transport.read_voltage_notification(
        address=address,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
    )
    return parse_voltage_notification(encrypted)
