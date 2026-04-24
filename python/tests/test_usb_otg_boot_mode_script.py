from __future__ import annotations

import subprocess
from pathlib import Path


def test_usb_otg_frame_helper_refresh_requires_existing_backing_image() -> None:
    image_path = "/var/lib/bm-gateway/usb-otg/missing.img"
    result = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-frame-test.sh",
            "refresh",
            "--image-path",
            image_path,
            "--gadget-name",
            "bmgw_test",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"backing image not found: {image_path}" in result.stderr


def test_usb_otg_frame_helper_rejects_image_paths_outside_safe_directory(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-frame-test.sh",
            "status",
            "--image-path",
            str(tmp_path / "unsafe.img"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "image path must be directly under /var/lib/bm-gateway/usb-otg" in result.stderr


def test_usb_otg_frame_helper_rejects_unsafe_gadget_names() -> None:
    result = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-frame-test.sh",
            "status",
            "--gadget-name",
            "../unsafe",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "gadget name must be a simple bmgw_* identifier" in result.stderr


def test_usb_otg_frame_helper_setup_detaches_before_rebuilding_backing_image() -> None:
    script_text = Path("rpi-setup/scripts/usb-otg-frame-test.sh").read_text(encoding="utf-8")
    setup_case = script_text.split("  setup)", maxsplit=1)[1].split("    ;;", maxsplit=1)[0]

    assert setup_case.index("detach_gadget") < setup_case.index("populate_image")


def test_usb_otg_frame_helper_copies_only_top_level_readable_files() -> None:
    script_text = Path("rpi-setup/scripts/usb-otg-frame-test.sh").read_text(encoding="utf-8")

    assert 'rm -f "${image_path}"' in script_text
    assert 'touch "${mount_dir}/.bmgw-write-test"' in script_text
    assert 'find "${mount_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +' in script_text
    assert 'source_find_args=("${source_dir}" -maxdepth 1 -type f -readable)' in script_text
    assert 'find "${source_find_args[@]}" -print -quit | grep -q .' in script_text
    assert 'find "${source_find_args[@]}" -exec cp' in script_text
    assert 'cp -R "${source_dir}/."' not in script_text


def test_usb_otg_frame_helper_limits_sudo_source_files_to_calling_user() -> None:
    script_text = Path("rpi-setup/scripts/usb-otg-frame-test.sh").read_text(encoding="utf-8")

    assert 'source_find_args+=(-user "${SUDO_UID}")' in script_text


def test_usb_otg_boot_mode_prepare_adds_managed_peripheral_overlay(tmp_path: Path) -> None:
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        "\n".join(
            [
                "arm_64bit=1",
                "",
                "[all]",
                "dtoverlay=vc4-kms-v3d",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "prepare",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    text = config_path.read_text(encoding="utf-8")
    assert "# BMGateway USB OTG image export: begin" in text
    assert "dtoverlay=dwc2,dr_mode=peripheral" in text
    assert "# BMGateway USB OTG image export: end" in text


def test_usb_otg_boot_mode_restore_removes_managed_overlay(tmp_path: Path) -> None:
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        "\n".join(
            [
                "[all]",
                "# BMGateway USB OTG image export: begin",
                "dtoverlay=dwc2,dr_mode=peripheral",
                "# BMGateway USB OTG image export: end",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "restore",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    text = config_path.read_text(encoding="utf-8")
    assert "BMGateway USB OTG image export" not in text
    assert "dtoverlay=dwc2,dr_mode=peripheral" not in text


def test_usb_otg_boot_mode_restore_preserves_previous_all_dwc2_line(tmp_path: Path) -> None:
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        "\n".join(
            [
                "[all]",
                "dtoverlay=dwc2,dr_mode=host",
                "",
            ]
        ),
        encoding="utf-8",
    )

    prepare = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "prepare",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert prepare.returncode == 0, prepare.stderr
    assert "# BMGateway previous: dtoverlay=dwc2,dr_mode=host" in config_path.read_text(
        encoding="utf-8"
    )

    restore = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "restore",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert restore.returncode == 0, restore.stderr
    text = config_path.read_text(encoding="utf-8")
    assert "dtoverlay=dwc2,dr_mode=host" in text
    assert "dtoverlay=dwc2,dr_mode=peripheral" not in text


def test_usb_otg_boot_mode_restore_removes_existing_unmanaged_peripheral_line(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        "\n".join(
            [
                "[all]",
                "dtoverlay=dwc2,dr_mode=peripheral",
                "",
            ]
        ),
        encoding="utf-8",
    )

    status = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "status",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert status.stdout.strip() == "prepared"

    restore = subprocess.run(
        [
            "bash",
            "rpi-setup/scripts/usb-otg-boot-mode.sh",
            "restore",
            "--config-path",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert restore.returncode == 0, restore.stderr
    text = config_path.read_text(encoding="utf-8")
    assert "dtoverlay=dwc2,dr_mode=peripheral" not in text
