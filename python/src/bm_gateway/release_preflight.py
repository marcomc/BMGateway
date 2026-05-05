"""Release-version consistency checks for local validation and deploys."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_CONCRETE_CHANGELOG_PATTERN = re.compile(r"^## \[(?!Unreleased\])([^\]]+)\]", re.M)
_UNRELEASED_SECTION_PATTERN = re.compile(r"^## \[Unreleased\].*?(?=^## \[|\Z)", re.M | re.S)
_MODULE_VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.M)
_README_RELEASE_PATTERN = re.compile(
    r"## Release Status.*?The current documented release is:\s*[-*] `([^`]+)`",
    re.S,
)


@dataclass(frozen=True)
class ReleaseVersionState:
    package_version: str
    module_version: str
    latest_concrete_version: str
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


def latest_concrete_version_from_changelog(text: str) -> str:
    matches = _CONCRETE_CHANGELOG_PATTERN.findall(text)
    if not matches:
        raise ValueError("No concrete release section found in CHANGELOG.md")
    return str(matches[0])


def unreleased_has_content_from_changelog(text: str) -> bool:
    match = _UNRELEASED_SECTION_PATTERN.search(text)
    if match is None:
        return False
    body = match.group(0).splitlines()[1:]
    return any(line.strip() for line in body)


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
    latest_concrete_version = latest_concrete_version_from_changelog(changelog_text)
    unreleased_has_content = unreleased_has_content_from_changelog(changelog_text)
    expected_working_version = (
        bump_last_component(latest_concrete_version)
        if unreleased_has_content
        else latest_concrete_version
    )

    documented_release_version = documented_release_version_from_readme(
        readme_path.read_text(encoding="utf-8")
    )

    return ReleaseVersionState(
        package_version=package_version,
        module_version=module_version,
        latest_concrete_version=latest_concrete_version,
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
        if state.unreleased_has_content:
            raise ValueError(
                "Unreleased changelog entries exist, so the working package version "
                f"must already be bumped to {state.expected_working_version}; "
                f"found {state.package_version}"
            )
        raise ValueError(
            "No unreleased changelog entries exist, so the working package version "
            f"must match the latest concrete release {state.latest_concrete_version}; "
            f"found {state.package_version}"
        )

    if state.documented_release_version is None:
        raise ValueError("README.md does not expose a current documented release version")

    if state.documented_release_version != state.latest_concrete_version:
        raise ValueError(
            "README.md release status is out of sync: "
            f"expected {state.latest_concrete_version}, "
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
            f"latest_release={state.latest_concrete_version}, "
            f"unreleased_has_content={str(state.unreleased_has_content).lower()}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
