from __future__ import annotations

from pathlib import Path

from bm_gateway.protocol_analysis import analyze_history_captures, decode_history_record


def _write_capture(path: Path, *, command: str, records: list[str]) -> None:
    payload = "".join(records)
    path.write_text(
        "\n".join(
            [
                '{"event":"probe_start","ts":"2026-04-27T18:00:00+00:00"}',
                (
                    '{"event":"command_result","ts":"2026-04-27T18:00:10+00:00",'
                    f'"command":"{command}","packets":['
                    '{"plaintext":"d1550506710000000000000000000000"},'
                    f'{{"plaintext":"{payload}"}}'
                    "]}"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_decode_history_record_uses_modern_bm6_bm7_layout() -> None:
    record = decode_history_record("53055120")

    assert record.raw == "53055120"
    assert record.voltage == 13.28
    assert record.soc == 85
    assert record.temperature == 18
    assert record.event == 0
    assert record.plausible is True


def test_analyze_history_captures_profiles_fields_and_sequence_overlap(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    old_records = ["53055120", "53055120", "4ee5a080", "00000001", "53d63120"]
    new_records = ["53155120", "53255120", *old_records]
    _write_capture(first, command="bm6_hist_d15505_b7_55_b4_0a", records=old_records)
    _write_capture(second, command="bm6_hist_d15505_b7_55_b4_0a", records=new_records)

    report = analyze_history_captures([first, second])

    command = report["commands"][0]
    assert command["selector"] == "b4_0a"
    assert command["record_count"] == 5
    assert command["plausible_count"] == 4
    assert command["marker_count"] == 1
    assert command["event_counts"] == {"0": 4, "1": 1}

    overlap = report["overlaps"][0]
    assert overlap == {
        "selector": "b4_0a",
        "old_capture": str(first),
        "new_capture": str(second),
        "old_record_count": 5,
        "new_record_count": 7,
        "old_in_new_offset": 2,
        "new_in_old_offset": None,
        "best_run_length": 5,
        "best_run_old_offset": 0,
        "best_run_new_offset": 2,
        "classification": "rolling_window",
    }
    assert report["selector_recommendations"] == [
        {
            "selector": "b4_0a",
            "status": "stitch_candidate",
            "reason": "same selector contains an earlier full window at offset 2",
        }
    ]


def test_analyze_history_captures_skips_empty_commands_when_comparing_overlap(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.jsonl"
    empty = tmp_path / "empty.jsonl"
    retry = tmp_path / "retry.jsonl"
    _write_capture(
        first,
        command="bm6_hist_d15505_b7_55_b7_55",
        records=["53055120", "4ee5a080"],
    )
    _write_capture(empty, command="bm6_hist_d15505_b7_55_b7_55", records=[])
    _write_capture(
        retry,
        command="bm6_hist_d15505_b7_55_b7_55",
        records=["53155120", "53055120", "4ee5a080"],
    )

    report = analyze_history_captures([first, empty, retry])

    assert [command["record_count"] for command in report["commands"]] == [2, 0, 3]
    assert len(report["overlaps"]) == 1
    assert report["overlaps"][0]["old_capture"] == str(first)
    assert report["overlaps"][0]["new_capture"] == str(retry)
    assert report["overlaps"][0]["old_in_new_offset"] == 1
