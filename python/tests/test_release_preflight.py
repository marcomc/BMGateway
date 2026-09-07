from __future__ import annotations

from pathlib import Path

import pytest
from bm_gateway.release_preflight import (
    bump_last_component,
    collect_release_version_state,
    main,
    validate_release_version_state,
)


def _write_release_files(
    root: Path,
    *,
    package_version: str,
    module_version: str,
    changelog_text: str,
    documented_release: str,
) -> None:
    (root / "python" / "src" / "bm_gateway").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "bm-gateway"',
                f'version = "{package_version}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "python" / "src" / "bm_gateway" / "__init__.py").write_text(
        f'__version__ = "{module_version}"\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    (root / "README.md").write_text(
        "\n".join(
            [
                "# BMGateway",
                "",
                "## Release Status",
                "",
                "The current documented release is:",
                "",
                f"- `{documented_release}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_bump_last_component_increments_patch_component() -> None:
    assert bump_last_component("0.2.2") == "0.2.3"
    assert bump_last_component("1.4") == "1.5"
    assert bump_last_component("7") == "8"


def test_collect_release_version_state_uses_latest_release_when_unreleased_is_empty(
    tmp_path: Path,
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.2.2",
        module_version="0.2.2",
        documented_release="0.2.2",
        changelog_text=(
            "# Changelog\n\n## [Unreleased]\n\n"
            "## [0.2.2] - 2026-05-03 - Released changes\n\n- Released changes.\n"
        ),
    )

    state = collect_release_version_state(tmp_path)

    assert state.latest_shipped_version == "0.2.2"
    assert state.active_release_version is None
    assert state.expected_working_version == "0.2.2"
    assert state.unreleased_has_content is False
    assert state.documented_release_version == "0.2.2"


def test_collect_release_version_state_uses_next_patch_when_unreleased_has_content(
    tmp_path: Path,
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.2.3",
        module_version="0.2.3",
        documented_release="0.2.2",
        changelog_text=(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.2.2] - 2026-05-03 - Released changes\n\n"
            "- Released changes.\n"
        ),
    )

    state = collect_release_version_state(tmp_path)

    assert state.latest_shipped_version == "0.2.2"
    assert state.active_release_version is None
    assert state.expected_working_version == "0.2.3"
    assert state.unreleased_has_content is True
    assert state.documented_release_version == "0.2.2"


def test_validate_release_version_state_rejects_stale_version_when_unreleased_has_content(
    tmp_path: Path,
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.2.2",
        module_version="0.2.2",
        documented_release="0.2.2",
        changelog_text=(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.2.2] - 2026-05-03 - Released changes\n\n"
            "- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="must already be bumped to 0.2.3"):
        validate_release_version_state(tmp_path)


def test_validate_release_version_state_accepts_current_repository() -> None:
    root = Path(__file__).resolve().parents[2]

    state = validate_release_version_state(root)

    assert state.package_version == "0.4.0"
    assert state.module_version == "0.4.0"
    assert state.documented_release_version == "0.4.0"
    assert state.active_release_version == "0.4.0"
    assert state.latest_shipped_version == "0.3.3"
    assert state.expected_working_version == "0.4.0"
    assert state.unreleased_has_content is False


def test_collect_release_version_state_uses_active_unreleased_release(
    tmp_path: Path,
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n"
            "- Released changes.\n"
        ),
    )

    state = validate_release_version_state(tmp_path)

    assert state.active_release_version == "0.4.0"
    assert state.latest_shipped_version == "0.3.3"
    assert state.expected_working_version == "0.4.0"
    assert state.unreleased_has_content is False


def test_active_release_rejects_nonempty_generic_unreleased_section(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "- Ambiguous next change.\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n"
            "- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="both an active release section and nonempty generic"):
        validate_release_version_state(tmp_path)


@pytest.mark.parametrize("heading", ["## [Unreleased] - Candidate", "## [Unreleased] candidate"])
def test_generic_unreleased_heading_must_not_have_a_suffix(tmp_path: Path, heading: str) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.2.2",
        module_version="0.2.2",
        documented_release="0.2.2",
        changelog_text=(
            f"# Changelog\n\n{heading}\n\n- Candidate fix under test.\n\n"
            "## [0.2.2] - 2026-05-03 - Released changes\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="Generic unreleased headings must use"):
        validate_release_version_state(tmp_path)


@pytest.mark.parametrize(
    "heading",
    ["## [0.5] - Unreleased - Candidate", "## [v0.5.0] - 2026-09-07 - Candidate"],
)
def test_current_release_heading_must_have_a_semantic_version(tmp_path: Path, heading: str) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            f"# Changelog\n\n{heading}\n\n- Candidate fix under test.\n\n"
            "## [0.4.0] - 2026-05-03 - Released changes\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="Current release heading must use"):
        validate_release_version_state(tmp_path)


@pytest.mark.parametrize(
    "heading",
    [
        "## [0.5.0] - TBD",
        "## [0.5.0] garbage",
        "## [0.5.0] - 2026-05-03",
    ],
)
def test_current_shipped_release_heading_must_be_dated_and_titled(
    tmp_path: Path, heading: str
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.5.0",
        module_version="0.5.0",
        documented_release="0.5.0",
        changelog_text=f"# Changelog\n\n{heading}\n\n- Released changes.\n",
    )

    with pytest.raises(ValueError, match="Current release heading must use"):
        validate_release_version_state(tmp_path)


def test_cli_reports_active_release_state(capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parents[2]

    assert main(["--root", str(root)]) == 0

    output = capsys.readouterr().out
    assert "working=0.4.0" in output
    assert "latest_shipped=0.3.3" in output
    assert "active_release=0.4.0" in output
    assert "generic_unreleased_has_content=false" in output
