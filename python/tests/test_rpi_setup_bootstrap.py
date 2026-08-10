from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def test_bootstrap_installs_reproducible_raspberry_pi_dependencies() -> None:
    script = Path("scripts/bootstrap-install.sh").read_text(encoding="utf-8")

    for package in (
        "avahi-daemon",
        "ca-certificates",
        "bluetooth",
        "bluez",
        "curl",
        "git",
        "make",
        "python3",
        "rfkill",
        "python3-venv",
    ):
        assert package in script

    for package in (
        "chromium",
        "dosfstools",
        "kmod",
        "libjpeg-dev",
        "msmtp",
        "msmtp-mta",
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
        "msmtp",
        "msmtp-mta",
        "python3-dev",
        "util-linux",
        "zlib1g-dev",
    ):
        assert package in script


def test_installers_preserve_an_existing_system_sendmail_transport() -> None:
    bootstrap = Path("scripts/bootstrap-install.sh").read_text(encoding="utf-8")
    service_installer = Path("rpi-setup/scripts/install-service.sh").read_text(encoding="utf-8")

    for script in (bootstrap, service_installer):
        assert 'system_sendmail_path="${BM_GATEWAY_SENDMAIL_PATH:-/usr/sbin/sendmail}"' in script
        assert 'if [[ ! -x "${system_sendmail_path}" ]]; then' in script
    assert "apt_packages+=(msmtp msmtp-mta)" in bootstrap
    assert "notification_packages=(msmtp msmtp-mta)" in service_installer
    manual_setup = Path("rpi-setup/manual-setup.md").read_text(encoding="utf-8")
    assert "if [[ ! -x /usr/sbin/sendmail ]]; then" in manual_setup
    assert "sudo apt install -y msmtp msmtp-mta" in manual_setup


def _service_installer_config_rewrite_program() -> str:
    script = Path("rpi-setup/scripts/install-service.sh").read_text(encoding="utf-8")
    heredoc_start = script.index(
        'python3 - <<\'PY\' "${config_path}" "${state_dir}" "${web_host}" '
        '"${web_port}" "${enable_home_assistant}" "${enable_web}"'
    )
    program_start = script.index("\n", heredoc_start) + 1
    program_end = script.index("\nPY\n\npython3 - <<'PY' \"${devices_path}\"", program_start)
    return script[program_start:program_end]


def _rewrite_service_config(tmp_path: Path, config_contents: str) -> dict[str, dict[str, object]]:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_contents, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _service_installer_config_rewrite_program(),
            str(config_path),
            str(tmp_path / "state"),
            "0.0.0.0",
            "80",
            "1",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def test_service_installer_preserves_explicit_bm200_archive_page_cap(tmp_path: Path) -> None:
    config = _rewrite_service_config(
        tmp_path,
        "[archive_sync]\nbm200_max_pages_per_sync = 3\n",
    )

    assert config["archive_sync"]["bm200_max_pages_per_sync"] == 3


def test_service_installer_defaults_absent_bm200_archive_page_cap_to_85(tmp_path: Path) -> None:
    config = _rewrite_service_config(tmp_path, "[archive_sync]\nenabled = true\n")

    assert config["archive_sync"]["bm200_max_pages_per_sync"] == 85


def test_imager_first_run_delegates_full_dependency_install_to_bootstrap() -> None:
    script = Path("rpi-setup/examples/imager/bm-gateway-first-run.sh").read_text(encoding="utf-8")

    assert "--skip-apt" not in script
