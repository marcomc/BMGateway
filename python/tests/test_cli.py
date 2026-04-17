from __future__ import annotations

import json
from pathlib import Path

import pytest
from bm_gateway import __version__, cli


def test_main_without_args_prints_focused_help(capsys: pytest.CaptureFixture[str]) -> None:
    expected_usage = "usage: bm-gateway [--version] [--config PATH] [--verbose] <command>"
    result = cli.main([])

    captured = capsys.readouterr()

    assert result == 0
    assert expected_usage in captured.out
    assert "Commands:" in captured.out
    assert "info" in captured.out


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main(["--version"])

    captured = capsys.readouterr()

    assert result == 0
    assert captured.out.strip() == __version__


def test_info_command_reads_config_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'app_name = "Example App"\ndefault_output = "json"\nverbose = false\n',
        encoding="utf-8",
    )

    result = cli.main(["--config", str(config_path), "info"])

    captured = capsys.readouterr()

    assert result == 0
    assert "app_name: Example App" in captured.out
    assert "default_output: json" in captured.out
    assert f"config_path: {config_path}" in captured.out


def test_info_command_can_emit_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('app_name = "Example App"\n', encoding="utf-8")

    result = cli.main(["--config", str(config_path), "info", "--json"])

    captured = capsys.readouterr()

    assert result == 0
    payload = json.loads(captured.out)
    assert payload["project_name"] == "BMGateway"
    assert payload["cli_name"] == "bm-gateway"
    assert payload["config"]["app_name"] == "Example App"
