# BMGateway Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first usable BMGateway slice with a real validation CLI, Home Assistant contract docs, and Raspberry Pi setup guidance.

**Architecture:** Keep the repository root aligned with the Python CLI template while moving the actual package into `python/` and treating Home Assistant, Raspberry Pi setup, and web work as peer components. The Python CLI is the executable contract layer for this slice: it reads TOML config, validates the device registry, and renders the MQTT/Home Assistant contract defined in repo docs.

**Tech Stack:** Python 3.11, `argparse`, `tomllib`, `dataclasses`, `pytest`, `ruff`, `mypy`, Markdown docs

---

## Task 1: Write the foundation spec and plan docs

**Files:**

- Create: `docs/specs/2026-04-17-foundation-spec.md`
- Create: `docs/superpowers/plans/2026-04-17-foundation-implementation.md`

- [ ] Step 1: Write the repository foundation spec.
- [ ] Step 2: Write the implementation plan.
- [ ] Step 3: Run `markdownlint --config .markdownlint.json docs/specs/2026-04-17-foundation-spec.md docs/superpowers/plans/2026-04-17-foundation-implementation.md`.

## Task 2: Capture the scaffold as the initial commit

**Files:**

- Modify: repository index and commit history

- [ ] Step 1: Stage the scaffold and docs.
- [ ] Step 2: Run `git status --short`.
- [ ] Step 3: Commit with `git commit -m "chore: initialize project scaffold"`.

## Task 3: Add failing tests for real CLI commands

**Files:**

- Modify: `python/tests/test_cli.py`

- [ ] Step 1: Add failing tests for `config show`, `config validate`,
  `devices list`, and `ha contract`.
- [ ] Step 2: Run `uv run pytest -q python/tests/test_cli.py`.
- [ ] Step 3: Confirm failures are due to missing commands or behavior.

## Task 4: Implement configuration, registry, and contract support

**Files:**

- Modify: `python/src/bm_gateway/cli.py`
- Modify: `python/src/bm_gateway/config.py`
- Create: `python/src/bm_gateway/contract.py`
- Create: `python/src/bm_gateway/device_registry.py`
- Create: `python/config/gateway.toml.example`
- Create: `python/config/devices.toml.example`

- [ ] Step 1: Implement typed gateway config loading and relative registry path
  resolution.
- [ ] Step 2: Implement device registry loading from TOML.
- [ ] Step 3: Implement Home Assistant topic/entity contract helpers.
- [ ] Step 4: Implement CLI commands against those helpers.
- [ ] Step 5: Run `uv run pytest -q python/tests/test_cli.py`.

## Task 5: Write Home Assistant and Raspberry Pi docs

**Files:**

- Create: `home-assistant/contract.md`
- Create: `rpi-setup/manual-setup.md`
- Modify: `home-assistant/README.md`
- Modify: `rpi-setup/README.md`

- [ ] Step 1: Document the MQTT topic and entity contract.
- [ ] Step 2: Write the initial Raspberry Pi manual setup guide.
- [ ] Step 3: Refresh component READMEs to reference those docs.
- [ ] Step 4: Run `markdownlint --config .markdownlint.json home-assistant/*.md rpi-setup/*.md`.

## Task 6: Validate and commit the implementation slice

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `TODO.md`
- Modify: git history

- [ ] Step 1: Update `CHANGELOG.md` and `TODO.md` for the delivered slice.
- [ ] Step 2: Run `make lint`.
- [ ] Step 3: Run `make test`.
- [ ] Step 4: Stage the implementation files.
- [ ] Step 5: Commit with `git commit -m "feat: add gateway contract tooling"`.
