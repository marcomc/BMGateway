from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from bm_gateway.drivers.bm300 import (
    BM300_POLL_PLAINTEXT,
    BleakBM300Transport,
    BM300Measurement,
    BM300ProtocolError,
    decrypt_bm300_payload,
    encrypt_bm300_payload,
    parse_bm300_plaintext_measurement,
    parse_bm300_voltage_notification,
    read_bm300_measurement,
)


def test_bm300_poll_request_matches_reference_ciphertext() -> None:
    encrypted = encrypt_bm300_payload(BM300_POLL_PLAINTEXT)

    assert encrypted == bytes.fromhex("586d7b2377c6924dcd750acb29f5bf8d")


def test_decrypt_bm300_payload_reverses_encrypt_bm300_payload() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")

    encrypted = encrypt_bm300_payload(plaintext)

    assert decrypt_bm300_payload(encrypted) == plaintext


def test_parse_bm300_plaintext_measurement_decodes_current_state() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")

    measurement = parse_bm300_plaintext_measurement(plaintext)

    assert measurement == BM300Measurement(
        voltage=13.4,
        soc=100,
        status_code=0,
        state="normal",
        temperature=23.0,
    )


def test_parse_bm300_plaintext_measurement_decodes_negative_temperature_and_state() -> None:
    plaintext = bytes.fromhex("d1550701170132050000000000000000")

    measurement = parse_bm300_plaintext_measurement(plaintext)

    assert measurement == BM300Measurement(
        voltage=12.8,
        soc=50,
        status_code=1,
        state="low",
        temperature=-23.0,
    )


def test_parse_bm300_plaintext_measurement_rejects_acknowledgements() -> None:
    plaintext = bytes.fromhex("d15507ff000000000000000000000000")

    with pytest.raises(BM300ProtocolError, match="acknowledgement"):
        parse_bm300_plaintext_measurement(plaintext)


def test_parse_bm300_voltage_notification_decrypts_before_parsing() -> None:
    plaintext = bytes.fromhex("d1550700170264053c0000000102ffff")
    encrypted = encrypt_bm300_payload(plaintext)

    measurement = parse_bm300_voltage_notification(encrypted)

    assert measurement.voltage == 13.4
    assert measurement.soc == 100
    assert measurement.state == "charging"
    assert measurement.temperature == 23.0


def test_read_bm300_measurement_preserves_scan_rssi() -> None:
    encrypted = encrypt_bm300_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))

    class FakeTransport:
        async def read_voltage_notification(
            self,
            *,
            address: str,
            adapter: str,
            timeout_seconds: float,
            scan_timeout_seconds: float,
        ) -> tuple[bytes, int | None]:
            assert address == "AA:BB:CC:DD:EE:FF"
            assert adapter == "hci0"
            assert timeout_seconds == 5.0
            assert scan_timeout_seconds == 3.0
            return encrypted, -67

    measurement = asyncio.run(
        read_bm300_measurement(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
            transport=FakeTransport(),
        )
    )

    assert measurement.voltage == 13.4
    assert measurement.rssi == -67


def test_bleak_bm300_transport_uses_configured_bluez_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()
    encrypted = encrypt_bm300_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))
    scanner_bluez_args: list[dict[str, str]] = []
    client_bluez_args: list[dict[str, str]] = []

    class FakeClient:
        def __init__(self, device: object, timeout: float, bluez: dict[str, str]) -> None:
            assert device is scanned_device
            assert timeout > 0
            client_bluez_args.append(dict(bluez))
            self._callback: Callable[[object | None, bytearray], None] | None = None

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(
            self,
            exc_type: object | None,
            exc: object | None,
            tb: object | None,
        ) -> None:
            return None

        async def start_notify(
            self,
            _char: str,
            callback: Callable[[object | None, bytearray], None],
        ) -> None:
            self._callback = callback

        async def write_gatt_char(self, _char: str, _data: bytes, response: bool) -> None:
            assert response is True
            assert self._callback is not None
            self._callback(None, bytearray(encrypted))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(
        address: str,
        timeout: float,
        bluez: dict[str, str],
    ) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        scanner_bluez_args.append(dict(bluez))
        return scanned_device

    monkeypatch.setattr(
        "bm_gateway.drivers.bm300.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm300.BleakClient", FakeClient)

    payload, rssi = asyncio.run(
        BleakBM300Transport().read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci1",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert parse_bm300_voltage_notification(payload).voltage == 13.4
    assert rssi is None
    assert scanner_bluez_args == [{"adapter": "hci1"}]
    assert client_bluez_args == [{"adapter": "hci1"}]
