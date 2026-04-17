"""BM200 Bluetooth protocol support."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from bleak import BleakClient
from Crypto.Cipher import AES

BM200_NOTIFY_CHARACTERISTIC = "0000fff4-0000-1000-8000-00805f9b34fb"
BM200_AES_KEY = bytes([108, 101, 97, 103, 101, 110, 100, 255, 254, 49, 56, 56, 50, 52, 54, 54])
BM200_BLOCK_SIZE = 16
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


class BM200Transport(Protocol):
    async def read_voltage_notification(
        self, *, address: str, adapter: str, timeout_seconds: float
    ) -> bytes: ...


def _create_cipher() -> Any:
    return AES.new(BM200_AES_KEY, AES.MODE_CBC, bytes(BM200_BLOCK_SIZE))


def _pad_payload(data: bytes) -> bytes:
    size = ((len(data) + BM200_BLOCK_SIZE - 1) // BM200_BLOCK_SIZE) * BM200_BLOCK_SIZE
    return data.ljust(size, b"\x00")


def encrypt_payload(plaintext: bytes) -> bytes:
    return bytes(_create_cipher().encrypt(_pad_payload(plaintext)))


def decrypt_payload(encrypted: bytes | bytearray) -> bytes:
    return bytes(_create_cipher().decrypt(bytes(encrypted)))


def parse_plaintext_measurement(plaintext: bytes) -> BM200Measurement:
    if len(plaintext) < 4 or plaintext[0] != 0xF5:
        raise ValueError("plaintext does not contain a BM200 voltage packet")

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


def parse_voltage_notification(encrypted: bytes | bytearray) -> BM200Measurement:
    return parse_plaintext_measurement(decrypt_payload(encrypted))


class BleakBM200Transport:
    async def read_voltage_notification(
        self, *, address: str, adapter: str, timeout_seconds: float
    ) -> bytes:
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def notification_handler(_: object, data: bytearray) -> None:
            queue.put_nowait(bytes(data))

        client = BleakClient(address, timeout=timeout_seconds, device=address)
        async with client:
            await client.start_notify(BM200_NOTIFY_CHARACTERISTIC, notification_handler)
            try:
                while True:
                    encrypted = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                    plaintext = decrypt_payload(encrypted)
                    if plaintext and plaintext[0] == 0xF5:
                        return encrypted
            finally:
                await client.stop_notify(BM200_NOTIFY_CHARACTERISTIC)


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
