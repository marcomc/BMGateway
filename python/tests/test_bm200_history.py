from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bm_gateway.drivers.bm200 import (
    BM200HistoryReading,
    decode_bm6_frame_payloads,
    decode_history_count_packet,
    decode_history_nibbles,
    default_bm6_history_reference_ts,
    encode_bm6_history_request,
    encode_history_count_request,
    encode_history_download_request,
    encrypt_bm6_payload,
    parse_bm6_history_items,
    parse_history_items,
)


def test_encode_history_requests_match_reference_protocol() -> None:
    assert encode_history_count_request() == bytes([0xE7, 0x01])
    assert encode_history_download_request(0x1234) == bytes(
        [0xE3, 0x00, 0x00, 0x00, 0x00, 0x12, 0x34]
    )


def test_encode_bm6_history_request_uses_byte_7_as_cumulative_page_count() -> None:
    assert encode_bm6_history_request(3) == bytes.fromhex("d1550500000000030000000000000000")


def test_encode_bm6_history_request_rejects_unbounded_page_count() -> None:
    with pytest.raises(ValueError, match="page_count"):
        encode_bm6_history_request(0)
    with pytest.raises(ValueError, match="page_count"):
        encode_bm6_history_request(256)


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


def test_decode_bm6_frame_payloads_decrypts_concatenated_frames_independently() -> None:
    first = bytes.fromhex("53258140532581405325814053258140")
    second = bytes.fromhex("53258140531581405325814053258140")
    encrypted = encrypt_bm6_payload(first) + encrypt_bm6_payload(second)

    assert decode_bm6_frame_payloads(encrypted) == [first, second]


def test_parse_bm6_history_items_decodes_newest_first_voltage_soc_and_temperature() -> None:
    reference_ts = datetime(2026, 4, 26, 18, 0, tzinfo=timezone.utc)

    readings = parse_bm6_history_items(
        bytes.fromhex("52b4c17052b4d16000000000"),
        reference_ts=reference_ts,
        page_selector=2,
    )

    assert readings == [
        BM200HistoryReading(
            ts="2026-04-26T18:00:00+00:00",
            voltage=13.23,
            min_crank_voltage=None,
            event_type=0,
            soc=76,
            temperature=23.0,
            raw_record="52b4c170",
            page_selector=2,
            record_index=0,
            timestamp_quality="estimated",
        ),
        BM200HistoryReading(
            ts="2026-04-26T17:58:00+00:00",
            voltage=13.23,
            min_crank_voltage=None,
            event_type=0,
            soc=77,
            temperature=22.0,
            raw_record="52b4d160",
            page_selector=2,
            record_index=1,
            timestamp_quality="estimated",
        ),
    ]


def test_default_bm6_history_reference_ts_uses_even_minute_with_timezone() -> None:
    now = datetime.fromisoformat("2026-04-26T20:17:42+02:00")

    reference_ts = default_bm6_history_reference_ts(now)

    assert reference_ts.isoformat(timespec="seconds") == "2026-04-26T20:16:00+02:00"
