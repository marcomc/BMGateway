from __future__ import annotations

from datetime import datetime, timezone

from bm_gateway.drivers.bm200 import (
    BM200HistoryReading,
    decode_history_count_packet,
    decode_history_nibbles,
    encode_history_count_request,
    encode_history_download_request,
    parse_history_items,
)


def test_encode_history_requests_match_reference_protocol() -> None:
    assert encode_history_count_request() == bytes([0xE7, 0x01])
    assert encode_history_download_request(0x1234) == bytes(
        [0xE3, 0x00, 0x00, 0x00, 0x00, 0x12, 0x34]
    )


def test_decode_history_count_packet_reads_three_byte_size() -> None:
    plaintext = bytes.fromhex("e7000010") + bytes(12)

    assert decode_history_count_packet(plaintext) == 16


def test_decode_history_nibbles_matches_reference_format() -> None:
    assert decode_history_nibbles(bytes.fromhex("4d411111"), "xxxkyyyp") == [1236, 1, 273, 1]


def test_parse_history_items_decodes_voltage_and_min_crank_values() -> None:
    reference_ts = datetime(2026, 4, 17, 18, 0, tzinfo=timezone.utc)

    readings = parse_history_items(
        bytes.fromhex("4d411111"),
        reference_ts=reference_ts,
    )

    assert readings == [
        BM200HistoryReading(
            ts="2026-04-17T18:00:00+00:00",
            voltage=12.36,
            min_crank_voltage=2.73,
            event_type=1,
        )
    ]
