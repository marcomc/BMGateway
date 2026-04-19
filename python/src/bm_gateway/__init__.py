"""Top-level package for BMGateway."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

__all__ = ["__build_timestamp__", "__version__", "display_version"]

__version__ = "0.1.0"
__build_timestamp__ = datetime.fromtimestamp(Path(__file__).stat().st_mtime).astimezone()


def display_version() -> str:
    built_at = __build_timestamp__.strftime("%Y-%m-%d %H:%M")
    return f"v{__version__} build {built_at}"
