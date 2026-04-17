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

## Runtime Modes

- `gateway.reader_mode = "fake"` keeps the deterministic development reader
- `gateway.reader_mode = "live"` enables explicit BLE polling for `bm200`
  devices
- `bm300pro` remains unsupported in live mode and will be reported as
  `unsupported`

## Notes

- The packaging metadata lives in the repository root `pyproject.toml`.
- The installed CLI name remains `bm-gateway`.
- The root `Makefile` is the supported entry point for linting, testing, and
  installation.
- The current runtime uses a fake reader to exercise the pipeline until the
  real Bluetooth adapter implementation is ready.
