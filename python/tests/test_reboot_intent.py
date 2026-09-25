from __future__ import annotations

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
