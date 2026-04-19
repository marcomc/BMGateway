# Developer Notes

This repository keeps the shared Python CLI template standards at the root, then
adapts them for a broader mono-repo.

## Included Defaults

- `uv` for Python environment and package management
- root-level `Makefile` orchestration
- strict Python checks for the packaged CLI
- Markdown and shell validation for repo-wide docs and helper scripts

## Intended Workflow

1. Treat the root as the project boundary.
2. Keep Python package work inside `python/`.
3. Add Home Assistant, Raspberry Pi, and web assets as sibling components.
4. Preserve `make install` as the durable user-facing installation path for the
   CLI unless distribution requirements change.

## Device Notes

- [BM6 / BM200 Integration Notes](2026-04-19-bm6-bm200-integration-notes.md)
