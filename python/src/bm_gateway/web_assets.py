"""Packaged web assets for the BMGateway UI."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=None)
def _read_asset_text(name: str) -> str:
    return files("bm_gateway").joinpath("assets", name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _read_asset_bytes(name: str) -> bytes:
    return files("bm_gateway").joinpath("assets", name).read_bytes()


def web_css_source() -> str:
    return _read_asset_text("web.css")


def chart_script_source() -> str:
    return _read_asset_text("chart.js")


def favicon_svg_source() -> str:
    return _read_asset_text("favicon.svg")


def apple_touch_icon_bytes() -> bytes:
    return _read_asset_bytes("apple-touch-icon.png")


def favicon_png_bytes() -> bytes:
    return _read_asset_bytes("favicon.png")


def web_manifest_source() -> str:
    return _read_asset_text("site.webmanifest")
