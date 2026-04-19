from __future__ import annotations

import asyncio
from typing import Callable

import pytest
from bm_gateway.drivers.bm200 import (
    BleakBM200Transport,
    BleakDeviceNotFoundError,
    BM200Measurement,
    decrypt_bm6_payload,
    decrypt_payload,
    encrypt_bm6_payload,
    encrypt_payload,
    parse_bm6_plaintext_measurement,
    parse_plaintext_measurement,
    parse_voltage_notification,
)


def test_parse_plaintext_measurement_decodes_voltage_soc_and_state() -> None:
    plaintext = bytes.fromhex("f54f923a000000000000000000000000")

    measurement = parse_plaintext_measurement(plaintext)

    assert measurement == BM200Measurement(
        voltage=12.73,
        soc=58,
        status_code=2,
        state="normal",
    )


def test_parse_voltage_notification_decrypts_before_parsing() -> None:
    plaintext = bytes.fromhex("f54f923a000000000000000000000000")
    encrypted = encrypt_payload(plaintext)

    measurement = parse_voltage_notification(encrypted)

    assert measurement.voltage == 12.73
    assert measurement.soc == 58
    assert measurement.state == "normal"


def test_decrypt_payload_reverses_encrypt_payload() -> None:
    plaintext = bytes.fromhex("f54f9048000000000000000000000000")

    encrypted = encrypt_payload(plaintext)

    assert decrypt_payload(encrypted) == plaintext


def test_parse_bm6_plaintext_measurement_decodes_voltage_and_soc() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")

    measurement = parse_bm6_plaintext_measurement(plaintext)

    assert measurement == BM200Measurement(
        voltage=13.4,
        soc=100,
        status_code=2,
        state="normal",
    )


def test_parse_voltage_notification_supports_bm6_packets() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")
    encrypted = encrypt_bm6_payload(plaintext)

    measurement = parse_voltage_notification(encrypted)

    assert measurement.voltage == 13.4
    assert measurement.soc == 100
    assert measurement.state == "normal"


def test_decrypt_bm6_payload_reverses_encrypt_bm6_payload() -> None:
    plaintext = bytes.fromhex("d1550700180064053c0000000102ffff")

    encrypted = encrypt_bm6_payload(plaintext)

    assert decrypt_bm6_payload(encrypted) == plaintext


def test_bleak_transport_scans_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    scanned_device = object()
    encrypted = encrypt_bm6_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))

    class FakeClient:
        def __init__(self, device: object, timeout: float) -> None:
            assert device is scanned_device
            assert timeout > 0
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
            assert response is False
            assert self._callback is not None
            self._callback(None, bytearray(encrypted))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(address: str, timeout: float) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        return scanned_device

    monkeypatch.setattr(
        "bm_gateway.drivers.bm200.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm200.BleakClient", FakeClient)

    transport = BleakBM200Transport()
    payload = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert parse_voltage_notification(payload).voltage == 13.4


def test_bleak_transport_raises_when_device_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_find_device_by_address(address: str, timeout: float) -> None:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        return None

    monkeypatch.setattr(
        "bm_gateway.drivers.bm200.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )

    transport = BleakBM200Transport()
    with pytest.raises(BleakDeviceNotFoundError):
        asyncio.run(
            transport.read_voltage_notification(
                address="AA:BB:CC:DD:EE:FF",
                adapter="hci0",
                timeout_seconds=5.0,
                scan_timeout_seconds=3.0,
            )
        )


def test_bleak_transport_retries_until_device_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    scanned_device = object()
    encrypted = encrypt_bm6_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))
    scan_results = iter([None, scanned_device])

    class FakeClient:
        def __init__(self, device: object, timeout: float) -> None:
            assert device is scanned_device
            assert timeout > 0
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
            assert response is False
            assert self._callback is not None
            self._callback(None, bytearray(encrypted))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(address: str, timeout: float) -> object | None:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        return next(scan_results)

    monkeypatch.setattr(
        "bm_gateway.drivers.bm200.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm200.BleakClient", FakeClient)

    transport = BleakBM200Transport()
    payload = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert parse_voltage_notification(payload).voltage == 13.4


def test_bleak_transport_retries_after_initial_notification_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()
    encrypted = encrypt_bm6_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))
    writes: list[bytes] = []

    class FakeClient:
        def __init__(self, device: object, timeout: float) -> None:
            assert device is scanned_device
            assert timeout > 0
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

        async def write_gatt_char(self, _char: str, data: bytes, response: bool) -> None:
            assert response is False
            writes.append(data)
            if len(writes) == 2:
                assert self._callback is not None
                self._callback(None, bytearray(encrypted))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(address: str, timeout: float) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout == 3.0
        return scanned_device

    async def fake_sleep(delay: float) -> None:
        assert delay > 0
        return None

    monkeypatch.setattr(
        "bm_gateway.drivers.bm200.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm200.BleakClient", FakeClient)
    monkeypatch.setattr("bm_gateway.drivers.bm200.asyncio.sleep", fake_sleep)

    transport = BleakBM200Transport()
    payload = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert len(writes) == 2
    assert parse_voltage_notification(payload).voltage == 13.4
