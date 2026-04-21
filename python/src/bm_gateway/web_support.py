"""Shared helpers for the BMGateway web layer."""

from __future__ import annotations

from pathlib import Path


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def default_curve_pairs() -> list[tuple[int, float]]:
    return [
        (100, 12.90),
        (90, 12.80),
        (80, 12.70),
        (70, 12.60),
        (60, 12.50),
        (50, 12.40),
        (40, 12.30),
        (30, 12.20),
        (20, 12.10),
        (10, 12.00),
        (0, 11.90),
    ]
