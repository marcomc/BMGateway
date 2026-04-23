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
        fake_bin / "sudo",
        "#!/bin/sh\n" + logger + 'exec "$@"\n',
    )
    _write_executable(
        fake_bin / "apt-get",
        "#!/bin/sh\n" + logger + "exit 0\n",
    )
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\n"
        + logger
        + 'if [ "$1" = "-fsSL" ] && [ "$3" = "-o" ]; then\n'
        + '  printf "#!/bin/sh\\nexit 0\\n" > "$4"\n'
        + "  exit 0\n"
        + "fi\n"
        + "exit 1\n",
    )
    _write_executable(
        fake_bin / "git",
        "#!/bin/sh\n"
        + logger
        + 'if [ "$1" = "clone" ]; then\n'
        + '  destination="$3"\n'
        + '  mkdir -p "$destination/.git"\n'
        + '  mkdir -p "$destination/rpi-setup/scripts"\n'
        + '  printf "#!/bin/sh\\nexit 0\\n" > "$destination/rpi-setup/scripts/install-service.sh"\n'
        + '  chmod +x "$destination/rpi-setup/scripts/install-service.sh"\n'
        + "  exit 0\n"
        + "fi\n"
        + 'if [ "$1" = "-C" ]; then\n'
        + "  exit 0\n"
        + "fi\n"
        + "exit 1\n",
    )
    _write_executable(
        fake_bin / "make",
        "#!/bin/sh\n" + logger + "exit 0\n",
    )
    _write_executable(
        fake_bin / "python3",
        "#!/bin/sh\n" + logger + 'printf "%s\\n" "$0"\n',
    )
    _write_executable(
        fake_bin / "hostnamectl",
        "#!/bin/sh\n" + logger + "exit 0\n",
    )

    return fake_bin, command_log


def test_bootstrap_install_script_clones_and_installs(tmp_path: Path) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)
    repo_dir = tmp_path / "BMGateway"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            str(script_path),
            "--repo-url",
            "https://example.invalid/BMGateway.git",
            "--repo-dir",
            str(repo_dir),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "apt-get update" in commands
    assert (
        "apt-get install -y bluetooth bluez curl git make python3 python3-venv dosfstools"
        in commands
    )
    assert "curl -fsSL https://astral.sh/uv/install.sh -o" in commands
    assert "git clone https://example.invalid/BMGateway.git" in commands
    assert f"make install PYTHON_VERSION={fake_bin / 'python3'}" in commands
    assert f"bash {repo_dir}/rpi-setup/scripts/install-service.sh --user" in commands
    assert "markdownlint" not in commands
    assert "shellcheck" not in commands


def test_bootstrap_install_script_can_skip_usb_otg_tools(tmp_path: Path) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)
    repo_dir = tmp_path / "BMGateway"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            str(script_path),
            "--repo-url",
            "https://example.invalid/BMGateway.git",
            "--repo-dir",
            str(repo_dir),
            "--skip-usb-otg-tools",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "apt-get install -y bluetooth bluez curl git make python3 python3-venv" in commands
    assert "dosfstools" not in commands


def test_bootstrap_install_script_updates_existing_checkout(tmp_path: Path) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)
    repo_dir = tmp_path / "BMGateway"
    (repo_dir / ".git").mkdir(parents=True)
    service_script = repo_dir / "rpi-setup" / "scripts" / "install-service.sh"
    service_script.parent.mkdir(parents=True)
    _write_executable(service_script, "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            str(script_path),
            "--repo-url",
            "https://example.invalid/BMGateway.git",
            "--repo-dir",
            str(repo_dir),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "git clone https://example.invalid/BMGateway.git" not in commands
    assert f"git -C {repo_dir} fetch --all --tags --prune" in commands
    assert f"git -C {repo_dir} pull --ff-only" in commands


def test_bootstrap_install_script_can_set_hostname(tmp_path: Path) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)
    repo_dir = tmp_path / "BMGateway"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [
            str(script_path),
            "--repo-url",
            "https://example.invalid/BMGateway.git",
            "--repo-dir",
            str(repo_dir),
            "--hostname",
            "garage-gateway",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "hostnamectl set-hostname garage-gateway" in commands


def test_bootstrap_install_script_uses_current_checkout_without_repo_url(
    tmp_path: Path,
) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(script_path), "--skip-apt", "--skip-uv", "--skip-services"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "git clone" not in commands
    assert "fetch --all --tags --prune" not in commands
    assert f"make install PYTHON_VERSION={fake_bin / 'python3'}" in commands


def test_bootstrap_install_script_uses_uv_from_local_bin_when_skip_uv_is_set(
    tmp_path: Path,
) -> None:
    script_path = Path("scripts/bootstrap-install.sh").resolve()
    fake_bin, command_log = _make_fake_environment(tmp_path)
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True)
    _write_executable(
        local_bin / "uv",
        "#!/bin/sh\n" + f'printf "%s\\n" "$0 $*" >> "{command_log}"\n' + "exit 0\n",
    )

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(script_path), "--skip-apt", "--skip-uv", "--skip-services"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr


def test_make_install_does_not_depend_on_maintainer_lint_tools() -> None:
    result = subprocess.run(
        ["make", "-n", "install"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "markdownlint not found" not in result.stdout
    assert "shellcheck not found" not in result.stdout


def test_make_install_finds_uv_from_local_bin_on_clean_path(tmp_path: Path) -> None:
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    _write_executable(local_bin / "uv", "#!/bin/sh\nexit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = "/usr/bin:/bin"

    result = subprocess.run(
        ["bash", "-lc", 'export PATH="$HOME/.local/bin:$PATH"; make install-deps'],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
