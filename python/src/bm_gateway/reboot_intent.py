"""Durable provenance for a BMGateway-requested host reboot."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


def reboot_intent_path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "reboot_intent.json"


def record_reboot_intent(state_dir: Path, boot_id: str, actions: list[str]) -> None:
    """Checkpoint the request before scheduling a reboot."""
    path = reboot_intent_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(
                {
                    "boot_id": boot_id,
                    "actions": sorted(set(actions)),
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
                handle,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def clear_reboot_intent(state_dir: Path) -> None:
    """Durably discard a failed or consumed request."""
    path = reboot_intent_path(state_dir)
    if not path.exists():
        return
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def reboot_request_for_boot(
    state_dir: Path, current_boot_id: str, previous_boot_id: str = ""
) -> str | None:
    """Return an unconsumed prior-boot request without claiming causality."""
    try:
        raw = json.loads(reboot_intent_path(state_dir).read_text(encoding="utf-8"))
        prior_boot_id = str(UUID(raw["boot_id"]))
        requested_at = datetime.fromisoformat(raw["requested_at"])
        actions = raw["actions"]
        if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions):
            return None
        if requested_at.tzinfo is None or prior_boot_id == str(UUID(current_boot_id)):
            return None
        if previous_boot_id and prior_boot_id != str(UUID(previous_boot_id)):
            return None
        if "wifi_reboot_requested" in actions:
            return "wifi"
        if any(
            item in actions for item in ("periodic_reboot_requested", "usb_otg_reboot_requested")
        ):
            return "other"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    return None
