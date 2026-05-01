from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from bm_gateway.drivers.bm300 import (
    BM300_POLL_PLAINTEXT,
    BleakBM7HistoryTransport,
    BleakBM300Transport,
    BM300HistoryReading,
    BM300Measurement,
    BM300ProtocolError,
    BM300TimeoutError,
    _collect_bm7_history_payload,
    decode_bm300_frame_payloads,
    decrypt_bm300_payload,
    default_bm7_history_reference_ts,
    encode_bm7_history_request,
    encrypt_bm300_payload,
    parse_bm7_history_items,
    parse_bm300_plaintext_measurement,
    parse_bm300_voltage_notification,
    read_bm300_history,
    read_bm300_history_selector,
    read_bm300_measurement,
)


def test_bm300_poll_request_matches_reference_ciphertext() -> None:
    encrypted = encrypt_bm300_payload(BM300_POLL_PLAINTEXT)

    assert encrypted == bytes.fromhex("586d7b2377c6924dcd750acb29f5bf8d")


def test_decrypt_bm300_payload_reverses_encrypt_bm300_payload() -> None:
    plaintext = bytes.fromhex("d1550700170064053c0000000102ffff")

    encrypted = encrypt_bm300_payload(plaintext)

    assert decrypt_bm300_payload(encrypted) == plaintext


def test_decode_bm300_frame_payloads_decrypts_concatenated_frames_independently() -> None:
    first = bytes.fromhex("53b620f053a620e053a620e053a620e0")
    second = bytes.fromhex("fffefe00000000000000000000000000")
    encrypted = encrypt_bm300_payload(first) + encrypt_bm300_payload(second)

    assert decode_bm300_frame_payloads(encrypted) == [first, second]


def test_encode_bm7_history_request_uses_byte_6_as_cumulative_selector() -> None:
    assert encode_bm7_history_request(3) == bytes.fromhex("d1550500000003000000000000000000")


def test_encode_bm7_history_request_rejects_unbounded_page_count() -> None:
    with pytest.raises(ValueError, match="page_count"):
        encode_bm7_history_request(0)
    with pytest.raises(ValueError, match="page_count"):
        encode_bm7_history_request(256)


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


def test_parse_bm7_history_items_decodes_newest_first_voltage_soc_and_temperature() -> None:
    reference_ts = datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc)

    readings = parse_bm7_history_items(
        bytes.fromhex("53b620f053a620e000000000"),
        reference_ts=reference_ts,
        page_selector=1,
    )

    assert readings == [
        BM300HistoryReading(
            ts="2026-04-26T18:54:00+00:00",
            voltage=13.39,
            min_crank_voltage=None,
            event_type=0,
            soc=98,
            temperature=15.0,
            raw_record="53b620f0",
            page_selector=1,
            record_index=0,
            timestamp_quality="estimated",
        ),
        BM300HistoryReading(
            ts="2026-04-26T18:52:00+00:00",
            voltage=13.38,
            min_crank_voltage=None,
            event_type=0,
            soc=98,
            temperature=14.0,
            raw_record="53a620e0",
            page_selector=1,
            record_index=1,
            timestamp_quality="estimated",
        ),
    ]


def test_collect_bm7_history_payload_stops_at_embedded_trailer() -> None:
    async def run() -> bytes:
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        await queue.put(encrypt_bm300_payload(bytes.fromhex("d1550503000000000000000000000000")))
        await queue.put(encrypt_bm300_payload(bytes.fromhex("53a620d053b620f0fffefe0000000000")))
        await queue.put(encrypt_bm300_payload(bytes.fromhex("d15507000d0062053a00000000000000")))
        return await _collect_bm7_history_payload(
            queue,
            deadline=asyncio.get_running_loop().time() + 1.0,
        )

    payload = asyncio.run(run())

    assert payload == bytes.fromhex("53a620d053b620f0")


def test_default_bm7_history_reference_ts_uses_even_minute_with_timezone() -> None:
    now = datetime.fromisoformat("2026-04-26T20:17:42+02:00")

    reference_ts = default_bm7_history_reference_ts(now)

    assert reference_ts.isoformat(timespec="seconds") == "2026-04-26T20:16:00+02:00"


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


def test_read_bm300_history_uses_bm7_transport() -> None:
    class FakeTransport:
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
            assert address == "AA:BB:CC:DD:EE:FF"
            assert adapter == "hci0"
            assert timeout_seconds == 5.0
            assert scan_timeout_seconds == 3.0
            assert reference_ts == datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc)
            assert page_count == 2
            return [
                BM300HistoryReading(
                    ts="2026-04-26T18:54:00+00:00",
                    voltage=13.39,
                    min_crank_voltage=None,
                    event_type=0,
                    soc=98,
                    temperature=15.0,
                    raw_record="53b620f0",
                    page_selector=2,
                    record_index=0,
                )
            ]

    readings = asyncio.run(
        read_bm300_history(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
            page_count=2,
            reference_ts=datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc),
            transport=FakeTransport(),
        )
    )

    assert readings[0].raw_record == "53b620f0"


def test_read_bm300_history_selector_uses_requested_selector_byte() -> None:
    class FakeTransport:
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
            assert address == "AA:BB:CC:DD:EE:FF"
            assert adapter == "hci0"
            assert timeout_seconds == 5.0
            assert scan_timeout_seconds == 3.0
            assert reference_ts == datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc)
            assert request == bytes.fromhex("d1550500000000030000000000000000")
            assert page_selector == 3
            return []

    readings = asyncio.run(
        read_bm300_history_selector(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci0",
            timeout_seconds=5.0,
            scan_timeout_seconds=3.0,
            selector_byte=7,
            selector_value=3,
            reference_ts=datetime(2026, 4, 26, 18, 54, tzinfo=timezone.utc),
            transport=FakeTransport(),
        )
    )

    assert readings == []


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


def test_bleak_bm300_transport_times_out_when_session_setup_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()

    class FakeClient:
        def __init__(self, device: object, timeout: float, bluez: dict[str, str]) -> None:
            assert device is scanned_device
            assert timeout > 0
            assert bluez == {"adapter": "hci1"}

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
            _ = callback
            await asyncio.sleep(3600)

        async def write_gatt_char(self, _char: str, _data: bytes, response: bool) -> None:
            _ = response
            raise AssertionError("write_gatt_char should not be reached")

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(
        address: str,
        timeout: float,
        bluez: dict[str, str],
    ) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        assert bluez == {"adapter": "hci1"}
        return scanned_device

    monkeypatch.setattr(
        "bm_gateway.drivers.bm300.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm300.BleakClient", FakeClient)

    with pytest.raises(BM300TimeoutError, match="AA:BB:CC:DD:EE:FF"):
        asyncio.run(
            BleakBM300Transport().read_voltage_notification(
                address="AA:BB:CC:DD:EE:FF",
                adapter="hci1",
                timeout_seconds=0.2,
                scan_timeout_seconds=0.1,
            )
        )


def test_bleak_bm7_history_transport_times_out_when_session_setup_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()

    class FakeClient:
        def __init__(self, device: object, timeout: float, bluez: dict[str, str]) -> None:
            assert device is scanned_device
            assert timeout > 0
            assert bluez == {"adapter": "hci1"}

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
            _ = callback
            await asyncio.sleep(3600)

        async def write_gatt_char(self, _char: str, data: bytes, response: bool) -> None:
            _ = (data, response)
            raise AssertionError("write_gatt_char should not be reached")

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(
        address: str,
        timeout: float,
        bluez: dict[str, str],
    ) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        assert bluez == {"adapter": "hci1"}
        return scanned_device

    monkeypatch.setattr(
        "bm_gateway.drivers.bm300.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm300.BleakClient", FakeClient)

    with pytest.raises(BM300TimeoutError, match="AA:BB:CC:DD:EE:FF"):
        asyncio.run(
            BleakBM7HistoryTransport().read_history(
                address="AA:BB:CC:DD:EE:FF",
                adapter="hci1",
                timeout_seconds=0.2,
                scan_timeout_seconds=0.1,
                reference_ts=datetime.fromisoformat("2026-04-26T18:54:00+00:00"),
                page_count=1,
            )
        )


def test_bleak_bm7_history_transport_downloads_cumulative_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_device = object()
    writes: list[bytes] = []

    class FakeClient:
        def __init__(self, device: object, timeout: float, bluez: dict[str, str]) -> None:
            assert device is scanned_device
            assert timeout > 0
            assert bluez == {"adapter": "hci1"}
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
            assert response is True
            assert self._callback is not None
            writes.append(data)
            if len(writes) == 1:
                self._callback(
                    None,
                    bytearray(
                        encrypt_bm300_payload(bytes.fromhex("d15507ff000000000000000000000000"))
                    ),
                )
            if len(writes) == 2:
                ack = encrypt_bm300_payload(bytes.fromhex("d1550503670000000000000000000000"))
                payload = encrypt_bm300_payload(bytes.fromhex("53b620f053a620e00000000000000000"))
                self._callback(None, bytearray(ack))
                self._callback(None, bytearray(payload))

        async def stop_notify(self, _char: str) -> None:
            return None

    async def fake_find_device_by_address(
        address: str,
        timeout: float,
        bluez: dict[str, str],
    ) -> object:
        assert address == "AA:BB:CC:DD:EE:FF"
        assert timeout > 0
        assert bluez == {"adapter": "hci1"}
        return scanned_device

    monkeypatch.setattr(
        "bm_gateway.drivers.bm300.BleakScanner.find_device_by_address",
        fake_find_device_by_address,
    )
    monkeypatch.setattr("bm_gateway.drivers.bm300.BleakClient", FakeClient)

    readings = asyncio.run(
        BleakBM7HistoryTransport().read_history(
            address="AA:BB:CC:DD:EE:FF",
            adapter="hci1",
            timeout_seconds=8.0,
            scan_timeout_seconds=3.0,
            reference_ts=datetime.fromisoformat("2026-04-26T18:54:00+00:00"),
            page_count=2,
        )
    )

    assert writes == [
        encrypt_bm300_payload(BM300_POLL_PLAINTEXT),
        encrypt_bm300_payload(encode_bm7_history_request(2)),
    ]
    assert [reading.raw_record for reading in readings] == ["53b620f0", "53a620e0"]
    assert [reading.soc for reading in readings] == [98, 98]
