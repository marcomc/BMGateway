# Python Component

This directory contains the packaged Python CLI and service code for
`BMGateway`.

## Layout

- `src/bm_gateway/` contains importable application code
- `tests/` contains Python test coverage
- `config/` contains example config and schema artifacts

## Current Commands

- `bm-gateway config show`
- `bm-gateway config validate`
- `bm-gateway devices list`
- `bm-gateway ha contract`
- `bm-gateway ha discovery`
- `bm-gateway run --once --dry-run`
- `bm-gateway web render --snapshot-file <path>`
- `bm-gateway web serve --snapshot-file <path>`

## Notes

- The packaging metadata lives in the repository root `pyproject.toml`.
- The installed CLI name remains `bm-gateway`.
- The root `Makefile` is the supported entry point for linting, testing, and
  installation.
- The current runtime uses a fake reader to exercise the pipeline until the
  real Bluetooth adapter implementation is ready.
