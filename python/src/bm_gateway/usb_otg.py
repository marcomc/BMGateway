"""USB OTG gadget detection helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

USB_OTG_DRIVE_HELPER_PATH = Path("/usr/local/bin/bm-gateway-usb-otg-frame-test")
USB_OTG_FRAME_RENDERER_UNSUPPORTED_REASON = (
    "USB OTG frame image export is not supported on this hardware because "
    "Chromium requires ARM NEON or ASIMD support."
)
USB_OTG_FRAME_RENDERER_ENABLE_ERROR = (
    "USB OTG picture-frame export is not supported on this Raspberry Pi because "
    "Chromium requires ARM NEON or ASIMD support"
)


def usb_otg_support_installed(
    *,
    drive_helper_path: Path = USB_OTG_DRIVE_HELPER_PATH,
) -> bool:
    mkfs_vfat_paths = (Path("/usr/sbin/mkfs.vfat"), Path("/sbin/mkfs.vfat"))
    return drive_helper_path.exists() and (
        shutil.which("mkfs.vfat") is not None or any(path.exists() for path in mkfs_vfat_paths)
    )


def usb_otg_device_controller_detected(sys_class_udc: Path = Path("/sys/class/udc")) -> bool:
    if not sys_class_udc.is_dir():
        return False
    return any(path.name for path in sys_class_udc.iterdir())


def usb_otg_frame_renderer_supported(cpuinfo_path: Path = Path("/proc/cpuinfo")) -> bool:
    try:
        text = cpuinfo_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    lower_text = text.lower()
    is_arm = any(marker in lower_text for marker in ("arm", "aarch64", "bcm2835", "raspberry pi"))
    if not is_arm:
        return True
    feature_tokens: set[str] = set()
    for line in lower_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"features", "flags"}:
            feature_tokens.update(value.strip().split())
    return bool({"neon", "asimd"} & feature_tokens)


def usb_otg_boot_mode_prepared(config_path: Path = Path("/boot/firmware/config.txt")) -> bool:
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "[all]":
            continue
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                break
            if stripped.startswith("dtoverlay=dwc2") and "dr_mode=peripheral" in stripped:
                return True
    return False
