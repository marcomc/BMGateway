"""Packaged web assets for the BMGateway UI."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=None)
def _read_asset_text(name: str) -> str:
    return files("bm_gateway").joinpath("assets", name).read_text(encoding="utf-8")


def web_css_source() -> str:
    return _read_asset_text("web.css")


def chart_script_source() -> str:
    return _read_asset_text("chart.js")
