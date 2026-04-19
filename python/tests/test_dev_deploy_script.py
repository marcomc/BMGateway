from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_fake_environment(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "command.log"
    command_log.write_text("", encoding="utf-8")

    logger = f'printf "%s\\n" "$0 $*" >> "{command_log}"\n'

    _write_executable(
        fake_bin / "ssh",
        "#!/bin/sh\n"
        + logger
        + f'while IFS= read -r line; do printf "%s\\n" "$line" >> "{command_log}"; done\n'
        + "exit 0\n",
    )
    _write_executable(
        fake_bin / "rsync",
        "#!/bin/sh\n" + logger + "exit 0\n",
    )

    return fake_bin, command_log


def test_dev_deploy_script_requires_target(tmp_path: Path) -> None:
    script_path = Path("scripts/dev-deploy.sh").resolve()
    fake_bin, _ = _make_fake_environment(tmp_path)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(script_path)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 1
    assert "Missing required --target argument" in result.stderr


def test_dev_deploy_script_syncs_checkout_and_refreshes_services(tmp_path: Path) -> None:
    script_path = Path("scripts/dev-deploy.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(script_path), "--target", "admin@example.com"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "bash -s -- /home/admin/BMGateway-dev" in commands
    assert "rsync -az --delete" in commands
    assert "--exclude .git" in commands
    assert "admin@example.com:/home/admin/BMGateway-dev/" in commands
    assert 'make install "PYTHON_VERSION=${python_path}"' in commands
    assert "systemctl is-active --quiet glances-web.service" in commands
    assert "service_args+=(--enable-glances)" in commands
    assert "systemctl is-active --quiet cockpit.socket" in commands
    assert "service_args+=(--enable-cockpit)" in commands
    assert 'install-service.sh "${service_args[@]}"' in commands


def test_dev_deploy_script_accepts_remote_dir_override(tmp_path: Path) -> None:
    script_path = Path("scripts/dev-deploy.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            str(script_path),
            "--target",
            "admin@example.com",
            "--remote-dir",
            "/srv/bm-gateway-dev",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "admin@example.com:/srv/bm-gateway-dev/" in commands
    assert 'cd "${remote_dir}"' in commands
