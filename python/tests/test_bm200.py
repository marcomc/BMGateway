from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from typing import Callable

import pytest
from bm_gateway.drivers.bm200 import (
    BleakBM6HistoryTransport,
    BleakBM200HistoryTransport,
    BleakBM200Transport,
    BleakDeviceNotFoundError,
    BM200Measurement,
    BM200TimeoutError,
    _collect_bm6_history_payload,
    decrypt_bm6_payload,
    decrypt_payload,
    encode_bm6_history_request,
    encode_history_count_request,
    encode_history_download_request,
    encrypt_bm6_payload,
    encrypt_payload,
    parse_bm6_plaintext_measurement,
    parse_history_items,
    parse_plaintext_measurement,
    parse_voltage_notification,
    read_bm200_measurement,
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
        status_code=0,
        state="normal",
        temperature=23.0,
    )


def test_parse_bm6_plaintext_measurement_treats_code_two_as_charging() -> None:
    plaintext = bytes.fromhex("d1550700120264059c0000000002ffff")

    measurement = parse_bm6_plaintext_measurement(plaintext)

    assert measurement == BM200Measurement(
        voltage=14.36,
        soc=100,
        status_code=2,
        state="charging",
        temperature=18.0,
    )


def test_parse_voltage_notification_supports_bm6_packets() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")
    encrypted = encrypt_bm6_payload(plaintext)

    measurement = parse_voltage_notification(encrypted)

    assert measurement.voltage == 13.4
    assert measurement.soc == 100
    assert measurement.state == "normal"
    assert measurement.temperature == 23.0


def test_read_bm200_measurement_preserves_scan_rssi() -> None:
    encrypted = encrypt_bm6_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))

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
        read_bm200_measurement(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
            transport=FakeTransport(),
        )
    )

    assert measurement.voltage == 13.4
    assert measurement.rssi == -67


def test_bleak_transport_reads_rssi_from_bluez_details() -> None:
    encrypted = encrypt_bm6_payload(bytes.fromhex("d1550700170064053c0000000102ffff"))

    class ScannedDevice:
        details = {"props": {"RSSI": -56}}

    scanned_device = ScannedDevice()

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

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "bm_gateway.drivers.bm200.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm200.BleakClient", FakeClient)
    try:
        payload, rssi = asyncio.run(
            BleakBM200Transport().read_voltage_notification(
                address="AA:BB:CC:DD:EE:FF",
                adapter="hci0",
                timeout_seconds=5.0,
                scan_timeout_seconds=3.0,
            )
        )
    finally:
        monkeypatch.undo()

    assert parse_voltage_notification(payload).voltage == 13.4
    assert rssi == -56


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
    payload, rssi = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert parse_voltage_notification(payload).voltage == 13.4
    assert rssi is None


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
    payload, rssi = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert parse_voltage_notification(payload).voltage == 13.4
    assert rssi is None


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
    payload, rssi = asyncio.run(
        transport.read_voltage_notification(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
        )
    )

    assert len(writes) == 2
    assert parse_voltage_notification(payload).voltage == 13.4
    assert rssi is None


def test_parse_history_items_decodes_item_count() -> None:
    readings = parse_history_items(
        b"\x00\x00\x00\x00" * 3,
        reference_ts=datetime.fromisoformat("2026-04-19T12:00:00"),
    )

    assert len(readings) == 3
    assert readings[0].ts == "2026-04-19T11:56:00"
    assert readings[-1].ts == "2026-04-19T12:00:00"


def test_bleak_history_transport_downloads_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    scanned_device = object()
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
            assert self._callback is not None
            writes.append(data)
            if len(writes) == 1:
                count_packet = encrypt_payload(bytes([0xE7, 0x00, 0x00, 0x08]))
                self._callback(None, bytearray(count_packet))
            elif len(writes) == 2:
                start_packet = encrypt_payload(bytes.fromhex("fffffe00000000000000000000000000"))
                data_packet = encrypt_payload(bytes.fromhex("00000000000000000000000000000000"))
                end_packet = encrypt_payload(bytes.fromhex("fffefe00001100000000000000000000"))
                self._callback(None, bytearray(start_packet))
                self._callback(None, bytearray(data_packet))
                self._callback(None, bytearray(end_packet))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(address: str, timeout: float) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
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

    transport = BleakBM200HistoryTransport()
    readings = asyncio.run(
        transport.read_history(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
            reference_ts=datetime.fromisoformat("2026-04-19T12:00:00"),
        )
    )

    assert writes[0] == encrypt_payload(encode_history_count_request())
    assert writes[1] == encrypt_payload(encode_history_download_request(8))
    assert len(readings) == 2


def test_bleak_bm6_history_transport_downloads_cumulative_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()
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
            assert self._callback is not None
            writes.append(data)
            if len(writes) == 1:
                self._callback(
                    None,
                    bytearray(
                        encrypt_bm6_payload(bytes.fromhex("d15507ff000000000000000000000000"))
                    ),
                )
            if len(writes) == 2:
                ack = encrypt_bm6_payload(bytes.fromhex("d1550502000000000000000000000000"))
                first_payload = encrypt_bm6_payload(
                    bytes.fromhex("52b4c17052b4d1600000000000000000")
                )
                self._callback(None, bytearray(ack))
                self._callback(None, bytearray(first_payload))

                async def emit_later() -> None:
                    await asyncio.sleep(1.1)
                    second_payload = encrypt_bm6_payload(
                        bytes.fromhex("52b4e160000000000000000000000000")
                    )
                    trailer = encrypt_bm6_payload(bytes.fromhex("fffefe00000000000000000000000000"))
                    assert self._callback is not None
                    self._callback(None, bytearray(second_payload))
                    self._callback(None, bytearray(trailer))

                asyncio.create_task(emit_later())

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

    readings = asyncio.run(
        BleakBM6HistoryTransport().read_history(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
            reference_ts=datetime.fromisoformat("2026-04-26T18:00:00+00:00"),
            page_count=2,
        )
    )

    assert writes == [
        encrypt_bm6_payload(bytes.fromhex("d1550700000000000000000000000000")),
        encrypt_bm6_payload(encode_bm6_history_request(2)),
    ]
    assert [reading.raw_record for reading in readings] == ["52b4c170", "52b4d160", "52b4e160"]
    assert [reading.soc for reading in readings] == [76, 77, 78]


def test_collect_bm6_history_payload_rejects_partial_payload_after_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_wait_for = asyncio.wait_for
    wait_calls = 0

    async def fake_wait_for(awaitable: Awaitable[object], timeout: float) -> object:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            return await original_wait_for(awaitable, timeout)
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise TimeoutError

    async def run() -> None:
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        await queue.put(
            encrypt_payload(
                bytes.fromhex("fffffe00000000000000000000000000")
                + bytes.fromhex("00112233445566778899aabbccddeeff")
            )
        )
        with pytest.raises(BM200TimeoutError, match="bm6 history"):
            await _collect_bm6_history_payload(
                queue,
                deadline=asyncio.get_running_loop().time() + 1.0,
            )

    monkeypatch.setattr("bm_gateway.drivers.bm200.asyncio.wait_for", fake_wait_for)

    asyncio.run(run())
