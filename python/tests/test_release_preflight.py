from __future__ import annotations

from pathlib import Path

import pytest
from bm_gateway.release_preflight import (
    bump_last_component,
    collect_release_version_state,
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
            "# Changelog\n\n## [Unreleased]\n\n## [0.2.2] - 2026-05-03\n\n- Released changes.\n"
        ),
    )

    state = collect_release_version_state(tmp_path)

    assert state.latest_concrete_version == "0.2.2"
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
            "## [0.2.2] - 2026-05-03\n\n"
            "- Released changes.\n"
        ),
    )

    state = collect_release_version_state(tmp_path)

    assert state.latest_concrete_version == "0.2.2"
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
            "## [0.2.2] - 2026-05-03\n\n"
            "- Released changes.\n"
        ),
    )

    with pytest.raises(ValueError, match="must already be bumped to 0.2.3"):
        validate_release_version_state(tmp_path)


def test_validate_release_version_state_accepts_current_repository() -> None:
    root = Path(__file__).resolve().parents[2]

    state = validate_release_version_state(root)

    assert state.package_version == "0.3.0"
