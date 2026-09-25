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


def boot_receipt_path(state_dir: Path) -> Path:
    return state_dir / "runtime" / "boot_receipt.json"


def _sync_directory(path: Path) -> None:
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def observe_boot(state_dir: Path, boot_id: str) -> str | None:
    """Durably capture the immediate predecessor's request on first observation.

    Callers serialize this with reboot scheduling using the watchdog transaction.
    The receipt is independent of notification delivery and clock synchronization.
    """
    if not boot_id:
        raise ValueError("Missing boot identity")
    try:
        boot_id = str(UUID(boot_id))
    except ValueError:
        # Runtime tests and alternate boot-ID providers may use opaque IDs.
        pass
    path = boot_receipt_path(state_dir)
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(prior, dict) or not isinstance(prior.get("boot_id"), str):
            raise ValueError("Invalid boot receipt")
        if prior.get("reboot_request") not in (None, "wifi", "other"):
            raise ValueError("Invalid boot receipt")
        if not isinstance(prior.get("previous_boot_id", ""), str):
            raise ValueError("Invalid boot receipt")
        try:
            prior["boot_id"] = str(UUID(prior["boot_id"]))
        except ValueError:
            pass
    except FileNotFoundError:
        prior = {"boot_id": "", "reboot_request": None}
    if prior["boot_id"] == boot_id:
        _sync_directory(path)
        request = prior["reboot_request"]
        return request if isinstance(request, str) else None
    request = (
        reboot_request_for_boot(state_dir, boot_id, prior["boot_id"]) if prior["boot_id"] else None
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(
                {
                    "boot_id": boot_id,
                    "previous_boot_id": prior["boot_id"],
                    "reboot_request": request,
                },
                handle,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return request


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
        _sync_directory(path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def has_reboot_intent_for_boot(state_dir: Path, boot_id: str) -> bool:
    """Return whether a durable request for this boot can be reused by a retry."""
    path = reboot_intent_path(state_dir)
    try:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
            os.fsync(handle.fileno())
    except FileNotFoundError:
        return False
    except json.JSONDecodeError:
        return False
    _sync_directory(path)
    try:
        if str(UUID(raw["boot_id"])) != str(UUID(boot_id)):
            return False
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    try:
        requested_at = datetime.fromisoformat(raw["requested_at"])
        actions = raw["actions"]
    except (ValueError, TypeError, KeyError):
        return False
    recognized = {
        "wifi_reboot_requested",
        "periodic_reboot_requested",
        "usb_otg_reboot_requested",
    }
    return (
        requested_at.tzinfo is not None
        and isinstance(actions, list)
        and bool(actions)
        and all(isinstance(action, str) and action in recognized for action in actions)
    )


def clear_reboot_intent(state_dir: Path, *, consumed_by_boot_id: str = "") -> None:
    """Durably discard a failed or consumed request."""
    path = reboot_intent_path(state_dir)
    if not path.exists():
        return
    if consumed_by_boot_id:
        receipt = json.loads(boot_receipt_path(state_dir).read_text(encoding="utf-8"))
        intent = json.loads(path.read_text(encoding="utf-8"))
        if str(UUID(receipt["boot_id"])) != str(UUID(consumed_by_boot_id)) or str(
            UUID(intent["boot_id"])
        ) != str(UUID(receipt["previous_boot_id"])):
            return
    path.unlink()
    _sync_directory(path)


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
        if not previous_boot_id or prior_boot_id != str(UUID(previous_boot_id)):
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
