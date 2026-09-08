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


@pytest.mark.parametrize("generic_body", ["", "- Ambiguous next change.\n"])
def test_active_release_rejects_any_generic_unreleased_section(
    tmp_path: Path, generic_body: str
) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n## [Unreleased]\n\n"
            f"{generic_body}\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n"
            "- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="both an active release section and generic"):
        validate_release_version_state(tmp_path)


def test_active_release_rejects_a_later_empty_generic_unreleased_section(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [Unreleased]\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="both an active release section and generic"):
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


@pytest.mark.parametrize("later_body", ["", "- Hidden pending change.\n"])
def test_generic_unreleased_heading_must_not_be_duplicated(tmp_path: Path, later_body: str) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.2.2",
        module_version="0.2.2",
        documented_release="0.2.2",
        changelog_text=(
            "# Changelog\n\n## [Unreleased]\n\n"
            f"## [Unreleased]\n\n{later_body}\n"
            "## [0.2.2] - 2026-05-03 - Released changes\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="more than one generic"):
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


def test_current_release_heading_rejects_unknown_bracketed_name(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n## [Next]\n\n- Hidden pending change.\n\n"
            "## [0.4.0] - 2026-05-03 - Released changes\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="Current release heading must use"):
        validate_release_version_state(tmp_path)


def test_current_release_heading_rejects_unknown_name_after_active_release(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [Next]\n\n- Hidden pending change.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="Current release heading must use"):
        validate_release_version_state(tmp_path)


def test_current_heading_validation_stops_after_latest_shipped_release(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n\n"
            "## [0.2.0]\n\n- Legacy history without a release title.\n"
        ),
    )

    assert validate_release_version_state(tmp_path).latest_shipped_version == "0.3.3"


@pytest.mark.parametrize(
    "legacy_heading",
    [
        "## [0.2.0] - Unreleased - Historical marker",
        "## [0.2.0] - Unreleased",
    ],
)
def test_legacy_active_marker_below_latest_shipped_release_is_ignored(
    tmp_path: Path, legacy_heading: str
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
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n\n"
            f"{legacy_heading}\n\n- Legacy history.\n"
        ),
    )

    assert validate_release_version_state(tmp_path).active_release_version == "0.4.0"


def test_legacy_generic_unreleased_section_below_latest_shipped_is_ignored(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.4.0",
        module_version="0.4.0",
        documented_release="0.4.0",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.4.0] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n\n"
            "## [Unreleased]\n\n- Historical marker.\n"
        ),
    )

    assert validate_release_version_state(tmp_path).active_release_version == "0.4.0"


@pytest.mark.parametrize(
    "legacy_history",
    [
        "## [Unreleased] - Historical marker\n\n- Legacy history.\n",
        "## [Unreleased]\n\n- Historical marker.\n\n## [Unreleased]\n\n- Older marker.\n",
    ],
)
def test_legacy_malformed_or_duplicate_generic_headings_are_ignored(
    tmp_path: Path, legacy_history: str
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
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n\n"
            f"{legacy_history}"
        ),
    )

    assert validate_release_version_state(tmp_path).active_release_version == "0.4.0"


def test_current_generic_unreleased_section_ignores_legacy_duplicate(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.3.4",
        module_version="0.3.4",
        documented_release="0.3.3",
        changelog_text=(
            "# Changelog\n\n"
            "## [Unreleased]\n\n- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n\n"
            "## [Unreleased]\n\n- Historical marker.\n"
        ),
    )

    assert validate_release_version_state(tmp_path).unreleased_has_content


@pytest.mark.parametrize("current_version", ["0.3.2", "0.3.3"])
def test_current_shipped_release_version_must_exceed_preserved_history(
    tmp_path: Path, current_version: str
) -> None:
    _write_release_files(
        tmp_path,
        package_version=current_version,
        module_version=current_version,
        documented_release=current_version,
        changelog_text=(
            "# Changelog\n\n"
            f"## [{current_version}] - 2026-09-08 - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - Legacy release marker\n\n- Preserved history.\n"
        ),
    )

    with pytest.raises(ValueError, match="must be newer than preserved history"):
        validate_release_version_state(tmp_path)


def test_current_shipped_release_version_allows_a_newer_boundary(tmp_path: Path) -> None:
    _write_release_files(
        tmp_path,
        package_version="0.3.4",
        module_version="0.3.4",
        documented_release="0.3.4",
        changelog_text=(
            "# Changelog\n\n"
            "## [0.3.4] - 2026-09-08 - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - Legacy release marker\n\n- Preserved history.\n"
        ),
    )

    assert validate_release_version_state(tmp_path).latest_shipped_version == "0.3.4"


@pytest.mark.parametrize("active_version", ["0.3.2", "0.3.3"])
def test_active_release_version_must_exceed_latest_shipped(
    tmp_path: Path, active_version: str
) -> None:
    _write_release_files(
        tmp_path,
        package_version=active_version,
        module_version=active_version,
        documented_release=active_version,
        changelog_text=(
            "# Changelog\n\n"
            f"## [{active_version}] - Unreleased - Candidate release\n\n"
            "- Candidate fix under test.\n\n"
            "## [0.3.3] - 2026-07-17 - Previous release\n\n- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="must be newer than the latest shipped"):
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
