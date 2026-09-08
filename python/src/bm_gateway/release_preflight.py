"""Release-version consistency checks for local validation and deploys."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_ACTIVE_RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\] - Unreleased - \S.*$",
    re.M,
)
_SHIPPED_RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2} - \S.*$",
    re.M,
)
_VERSIONED_CHANGELOG_HEADING_PATTERN = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\](.*)$",
    re.M,
)
_RELEASE_HEADING_CANDIDATE_PATTERN = re.compile(r"^## \[([^]]+)\](.*)$", re.M)
_UNRELEASED_SECTION_PATTERN = re.compile(
    r"^## \[Unreleased\]\s*$.*?(?=^## \[|\Z)",
    re.M | re.S,
)
_GENERIC_UNRELEASED_HEADING_PATTERN = re.compile(r"^## \[Unreleased\](.*)$", re.M)
_MODULE_VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.M)
_README_RELEASE_PATTERN = re.compile(
    r"## Release Status.*?The current documented release is:\s*[-*] `([^`]+)`",
    re.S,
)


@dataclass(frozen=True)
class ReleaseVersionState:
    package_version: str
    module_version: str
    latest_shipped_version: str
    active_release_version: str | None
    expected_working_version: str
    documented_release_version: str | None
    unreleased_has_content: bool


def bump_last_component(version: str) -> str:
    parts = version.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Unsupported version format: {version}")
    bumped = [int(part) for part in parts]
    bumped[-1] += 1
    return ".".join(str(part) for part in bumped)


def active_release_version_from_changelog(text: str) -> str | None:
    current_prefix = _current_release_prefix(text)
    active_versions = _ACTIVE_RELEASE_HEADING_PATTERN.findall(current_prefix)
    malformed_active = [
        heading
        for heading in _VERSIONED_CHANGELOG_HEADING_PATTERN.finditer(current_prefix)
        if heading.group(2).startswith(" - Unreleased")
        and _ACTIVE_RELEASE_HEADING_PATTERN.fullmatch(heading.group(0)) is None
    ]
    if malformed_active:
        raise ValueError("Active release headings must use: ## [X.Y.Z] - Unreleased - Title")
    if len(active_versions) > 1:
        raise ValueError("CHANGELOG.md contains more than one active release section")
    return str(active_versions[0]) if active_versions else None


def _first_shipped_release_heading(text: str) -> re.Match[str] | None:
    return _SHIPPED_RELEASE_HEADING_PATTERN.search(text)


def _current_release_prefix(text: str) -> str:
    shipped = _first_shipped_release_heading(text)
    return text if shipped is None else text[: shipped.start()]


def validate_current_release_heading(text: str) -> None:
    """Reject malformed current release candidates without rewriting history."""
    for heading in _RELEASE_HEADING_CANDIDATE_PATTERN.finditer(text):
        version, _suffix = heading.groups()
        if version == "Unreleased":
            continue
        if _ACTIVE_RELEASE_HEADING_PATTERN.fullmatch(heading.group(0)) is not None:
            continue
        if _SHIPPED_RELEASE_HEADING_PATTERN.fullmatch(heading.group(0)) is not None:
            return
        raise ValueError(
            "Current release heading must use: "
            "## [Unreleased], ## [X.Y.Z] - Unreleased - Title, or "
            "## [X.Y.Z] - YYYY-MM-DD - Title"
        )


def latest_shipped_version_from_changelog(text: str) -> str:
    shipped = _first_shipped_release_heading(text)
    if shipped is None:
        raise ValueError("No shipped release section found in CHANGELOG.md")
    version = str(shipped.group(1))
    historical_versions = _VERSIONED_CHANGELOG_HEADING_PATTERN.findall(text[shipped.end() :])
    if any(
        version_key(version) <= version_key(historical) for historical, _ in historical_versions
    ):
        raise ValueError("Current shipped release version must be newer than preserved history")
    return version


def generic_unreleased_sections_from_changelog(text: str) -> list[re.Match[str]]:
    current_prefix = _current_release_prefix(text)
    malformed_headings = [
        heading
        for heading in _GENERIC_UNRELEASED_HEADING_PATTERN.finditer(current_prefix)
        if heading.group(1).strip()
    ]
    if malformed_headings:
        raise ValueError("Generic unreleased headings must use: ## [Unreleased]")
    sections = list(_UNRELEASED_SECTION_PATTERN.finditer(current_prefix))
    if len(sections) > 1:
        raise ValueError("CHANGELOG.md contains more than one generic [Unreleased] section")
    return sections


def unreleased_has_content_from_changelog(text: str) -> bool:
    sections = generic_unreleased_sections_from_changelog(text)
    if not sections:
        return False
    body = sections[0].group(0).splitlines()[1:]
    return any(line.strip() for line in body)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(component) for component in version.split("."))


def documented_release_version_from_readme(text: str) -> str | None:
    match = _README_RELEASE_PATTERN.search(text)
    if match is None:
        return None
    return match.group(1).strip()


def collect_release_version_state(root: Path) -> ReleaseVersionState:
    pyproject_path = root / "pyproject.toml"
    module_path = root / "python" / "src" / "bm_gateway" / "__init__.py"
    readme_path = root / "README.md"
    changelog_path = root / "CHANGELOG.md"

    with pyproject_path.open("rb") as handle:
        pyproject = tomllib.load(handle)
    package_version = str(pyproject["project"]["version"])

    module_text = module_path.read_text(encoding="utf-8")
    module_match = _MODULE_VERSION_PATTERN.search(module_text)
    if module_match is None:
        raise ValueError("Could not find __version__ in python/src/bm_gateway/__init__.py")
    module_version = module_match.group(1)

    changelog_text = changelog_path.read_text(encoding="utf-8")
    validate_current_release_heading(changelog_text)
    active_release_version = active_release_version_from_changelog(changelog_text)
    latest_shipped_version = latest_shipped_version_from_changelog(changelog_text)
    unreleased_has_content = unreleased_has_content_from_changelog(changelog_text)
    generic_unreleased_present = bool(generic_unreleased_sections_from_changelog(changelog_text))
    if active_release_version is not None and generic_unreleased_present:
        raise ValueError(
            "CHANGELOG.md cannot contain both an active release section and generic [Unreleased]"
        )
    if active_release_version is not None and version_key(active_release_version) <= version_key(
        latest_shipped_version
    ):
        raise ValueError(
            "Active changelog release version must be newer than the latest shipped release"
        )
    if active_release_version is not None:
        expected_working_version = active_release_version
    elif unreleased_has_content:
        expected_working_version = bump_last_component(latest_shipped_version)
    else:
        expected_working_version = latest_shipped_version

    documented_release_version = documented_release_version_from_readme(
        readme_path.read_text(encoding="utf-8")
    )

    return ReleaseVersionState(
        package_version=package_version,
        module_version=module_version,
        latest_shipped_version=latest_shipped_version,
        active_release_version=active_release_version,
        expected_working_version=expected_working_version,
        documented_release_version=documented_release_version,
        unreleased_has_content=unreleased_has_content,
    )


def validate_release_version_state(root: Path) -> ReleaseVersionState:
    state = collect_release_version_state(root)

    if state.package_version != state.module_version:
        raise ValueError(
            "Package version mismatch: "
            f"pyproject.toml has {state.package_version}, "
            f"but python/src/bm_gateway/__init__.py has {state.module_version}"
        )

    if state.package_version != state.expected_working_version:
        if state.active_release_version is not None:
            raise ValueError(
                "An active changelog release exists, so the working package version "
                f"must match {state.active_release_version}; found {state.package_version}"
            )
        if state.unreleased_has_content:
            raise ValueError(
                "Unreleased changelog entries exist, so the working package version "
                f"must already be bumped to {state.expected_working_version}; "
                f"found {state.package_version}"
            )
        raise ValueError(
            "No unreleased changelog entries exist, so the working package version "
            f"must match the latest shipped release {state.latest_shipped_version}; "
            f"found {state.package_version}"
        )

    if state.documented_release_version is None:
        raise ValueError("README.md does not expose a current documented release version")

    expected_documented_version = state.active_release_version or state.latest_shipped_version
    if state.documented_release_version != expected_documented_version:
        raise ValueError(
            "README.md release status is out of sync: "
            f"expected {expected_documented_version}, "
            f"found {state.documented_release_version}"
        )

    return state


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "CHANGELOG.md").exists():
            return candidate
    raise ValueError(f"Could not locate repository root from {start}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    root = _repo_root(args.root.resolve())
    state = validate_release_version_state(root)
    if not args.quiet:
        print(
            "Release version preflight passed: "
            f"working={state.package_version}, "
            f"latest_shipped={state.latest_shipped_version}, "
            f"active_release={state.active_release_version or 'none'}, "
            "generic_unreleased_has_content="
            f"{str(state.unreleased_has_content).lower()}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
