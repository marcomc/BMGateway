from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bm_gateway import reboot_intent


@pytest.mark.parametrize("failed_sync", [1, 2])
def test_intent_checkpoint_failure_before_or_after_replace_is_clearable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_sync: int
) -> None:
    original_fsync = os.fsync
    sync_count = 0

    def fail_selected_sync(descriptor: int) -> None:
        nonlocal sync_count
        sync_count += 1
        if sync_count == failed_sync:
            raise OSError("checkpoint failed")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_selected_sync)

    with pytest.raises(OSError, match="checkpoint failed"):
        reboot_intent.record_reboot_intent(tmp_path, "a" * 32, ["wifi_reboot_requested"])

    path = reboot_intent.reboot_intent_path(tmp_path)
    assert path.exists() is (failed_sync == 2)
    reboot_intent.clear_reboot_intent(tmp_path)
    assert not path.exists()


@pytest.mark.parametrize("failed_sync", [1, 2])
def test_boot_receipt_checkpoint_retry_preserves_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_sync: int
) -> None:
    previous_boot = "a" * 32
    current_boot = "b" * 32
    reboot_intent.observe_boot(tmp_path, previous_boot)
    reboot_intent.record_reboot_intent(tmp_path, previous_boot, ["wifi_reboot_requested"])
    original_fsync = os.fsync
    sync_count = 0

    def fail_selected_sync(descriptor: int) -> None:
        nonlocal sync_count
        sync_count += 1
        if sync_count == failed_sync:
            raise OSError("receipt checkpoint failed")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_selected_sync)
    with pytest.raises(OSError, match="receipt checkpoint failed"):
        reboot_intent.observe_boot(tmp_path, current_boot)
    monkeypatch.setattr(os, "fsync", original_fsync)

    assert reboot_intent.observe_boot(tmp_path, current_boot) == "wifi"
    assert reboot_intent.observe_boot(tmp_path, "c" * 32) is None


def test_missing_prior_receipt_fails_closed(tmp_path: Path) -> None:
    reboot_intent.record_reboot_intent(tmp_path, "a" * 32, ["wifi_reboot_requested"])

    assert reboot_intent.observe_boot(tmp_path, "b" * 32) is None
    assert reboot_intent.observe_boot(tmp_path, "c" * 32) is None


def test_only_valid_current_boot_request_is_reused(tmp_path: Path) -> None:
    current = "a" * 32
    path = reboot_intent.reboot_intent_path(tmp_path)
    assert not reboot_intent.has_reboot_intent_for_boot(tmp_path, current)
    reboot_intent.record_reboot_intent(tmp_path, current, ["wifi_reboot_requested"])
    assert reboot_intent.has_reboot_intent_for_boot(tmp_path, current)
    assert not reboot_intent.has_reboot_intent_for_boot(tmp_path, "b" * 32)
    raw = json.loads(path.read_text())
    raw["actions"] = ["unknown_action"]
    path.write_text(json.dumps(raw))
    assert not reboot_intent.has_reboot_intent_for_boot(tmp_path, current)
    path.write_text("{invalid")
    assert not reboot_intent.has_reboot_intent_for_boot(tmp_path, current)
