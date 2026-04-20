# Project Agent Notes

## Project Identity

- Project name: `BMGateway`
- Python package: `bm_gateway`
- Installed CLI: `bm-gateway`
- Installed web CLI: `bm-gateway-web`
- Module entry point: `python -m bm_gateway`
- Default user config path: `~/.config/bm-gateway/config.toml`
- Default standalone runtime path: `~/.local/share/bm-gateway/venv`
- Default user-facing binary path: `~/.local/bin/bm-gateway`
- Default user-facing web binary path: `~/.local/bin/bm-gateway-web`
- Repository shape: mono-repo with first-class `python/`, `home-assistant/`,
  `rpi-setup/`, and `web/` directories

## New Chat Bootstrap

At the start of every new AI agent chat for this repository, read:

1. `README.md`
2. `Makefile`
3. `pyproject.toml`
4. `CHANGELOG.md`
5. `TODO.md`
6. `python/README.md`
7. `docs/specs/2026-04-17-foundation-spec.md`
8. `docs/architecture/2026-04-20-shared-core-separate-web-runtime-plan.md`
9. `home-assistant/contract.md`
10. `rpi-setup/manual-setup.md`

## Development Rules

- Keep the project installable as a packaged Python CLI.
- Keep importable application code under `python/src/bm_gateway/`.
- Keep tests under `python/tests/`.
- Prefer focused modules instead of one large `cli.py`.
- Keep `python -m bm_gateway` working.
- Preserve the standalone install behavior of `make install`.
- Keep Home Assistant assets under `home-assistant/`.
- Keep Raspberry Pi setup documentation and automation under `rpi-setup/`.
- Keep shared web implementation code under `python/src/bm_gateway/`.
- Keep web product notes and non-packaged web assets under `web/`.
- Keep the CLI contract aligned with `home-assistant/contract.md`.
- For remote development deployments, use
  `make dev-deploy TARGET=admin@host` from the repository root.
- Keep remote dev deploy guidance generic in repo docs; do not commit personal
  hostnames.

## Live Validation Rules

- This project currently has no separate live development environment.
- Treat the main gateway host as the only real integration target for live
  validation.
- For changes that can affect appliance behavior, deploy to the gateway and
  verify there after local checks pass.

Practical deployment rule:

| Change type | Deploy every time? |
| --- | --- |
| Docs only | No |
| Pure unit-test/internal refactor with full local coverage | Usually no |
| Anything touching CLI behavior, packaging, `systemd`, install scripts, web entrypoints, config handling, BLE/runtime, MQTT, or persistence | Yes |

## Quality Gates

Use `make check` as the default maintainer validation command.

Expected checks:

- `uv run pytest -q`
- `uv run ruff check python/src python/tests`
- `uv run ruff format --check python/src python/tests`
- `uv run mypy python/src python/tests`
- `markdownlint --config .markdownlint.json README.md CHANGELOG.md TODO.md AGENTS.md docs/*.md python/*.md home-assistant/*.md rpi-setup/*.md rpi-setup/ansible/*.md web/*.md`
- `shellcheck --enable=all scripts/*.sh`

## Documentation Rules

- Keep `README.md` accurate for end users.
- Keep component `README.md` files accurate for contributors.
- Keep `CHANGELOG.md` updated in `Unreleased` for user-visible changes.
- Remove completed items from `TODO.md` when they ship.
- Update config documentation when adding or changing config keys.
- When code changes add, remove, or materially alter functionality or
  operational behavior, update the relevant documentation without waiting for a
  separate user request.
- Prefer a single canonical document per topic and link to it instead of
  duplicating the same guidance across multiple files.
- Keep documentation organized according to project standards: place new
  information in the most appropriate canonical document, maintain sensible
  grouping and section hierarchy, and move or reshape content when the current
  location or structure is no longer the best fit.

## Release Hygiene

When cutting a release, update the version consistently in:

- `pyproject.toml`
- `python/src/bm_gateway/__init__.py`
- `CHANGELOG.md`
- tests that assert the version string
