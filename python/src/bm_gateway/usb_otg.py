"""USB OTG gadget detection helpers."""

from __future__ import annotations

from pathlib import Path


def usb_otg_device_controller_detected(sys_class_udc: Path = Path("/sys/class/udc")) -> bool:
    if not sys_class_udc.is_dir():
        return False
    return any(path.name for path in sys_class_udc.iterdir())
