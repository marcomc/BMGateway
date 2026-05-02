from __future__ import annotations

from pathlib import Path


def test_bootstrap_installs_reproducible_raspberry_pi_dependencies() -> None:
    script = Path("scripts/bootstrap-install.sh").read_text(encoding="utf-8")

    for package in (
        "ca-certificates",
        "bluetooth",
        "bluez",
        "curl",
        "git",
        "make",
        "python3",
        "python3-venv",
    ):
        assert package in script

    for package in (
        "chromium",
        "dosfstools",
        "kmod",
        "libjpeg-dev",
        "python3-dev",
        "util-linux",
        "zlib1g-dev",
    ):
        assert package in script


def test_service_installer_installs_usb_otg_helper_dependencies() -> None:
    script = Path("rpi-setup/scripts/install-service.sh").read_text(encoding="utf-8")

    for package in (
        "chromium",
        "dosfstools",
        "kmod",
        "libjpeg-dev",
        "python3-dev",
        "util-linux",
        "zlib1g-dev",
    ):
        assert package in script


def test_imager_first_run_delegates_full_dependency_install_to_bootstrap() -> None:
    script = Path("rpi-setup/examples/imager/bm-gateway-first-run.sh").read_text(encoding="utf-8")

    assert "--skip-apt" not in script
