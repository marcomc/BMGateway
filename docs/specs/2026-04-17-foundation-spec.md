# BMGateway Foundation Spec

## Summary

`BMGateway` is a mono-repo for a Raspberry Pi based battery monitor gateway.
The first delivery focuses on repository boundaries, a real Python CLI for
configuration and integration contract inspection, a documented Home Assistant
contract, and a manual Raspberry Pi setup guide.

## Goals

- Keep `python/`, `home-assistant/`, `rpi-setup/`, and `web/` as first-class
  top-level components.
- Preserve the shared Python CLI template standards at the repository root.
- Replace the placeholder Python CLI behavior with commands that validate the
  gateway configuration and expose the Home Assistant contract.
- Define a durable Home Assistant MQTT contract that future service code can
  implement without guessing.
- Provide a manual Raspberry Pi setup guide that can later be translated into
  Ansible.

## Non-Goals

- Building the Bluetooth polling runtime in this slice.
- Implementing the web interface in this slice.
- Automating Raspberry Pi provisioning in this slice.
- Committing to Docker for the web stack in this slice.

## Repository Boundaries

### `python/`

Owns the packaged Python CLI, configuration schema, example registry files, and
tests. The root `pyproject.toml` packages code from `python/src/`.

### `home-assistant/`

Owns MQTT topic conventions, discovery payload examples, entity definitions, and
Home Assistant specific notes.

### `rpi-setup/`

Owns manual Raspberry Pi setup instructions, operational notes, and future
automation assets under `rpi-setup/ansible/`.

### `web/`

Owns the future local web interface and remains a reserved placeholder in this
slice.

## Python CLI Scope

The Python CLI must provide immediately useful commands:

- `config show`: print the resolved gateway configuration
- `config validate`: validate the gateway config and referenced device registry
- `devices list`: inspect configured devices from the registry file
- `ha contract`: print the expected Home Assistant MQTT topics and entities for
  the configured gateway

The CLI is a planning and validation tool in this slice, not the runtime
service itself.

## Configuration Model

The configuration remains TOML-based to stay aligned with the project template.

The config file must support these top-level tables:

- `[gateway]`
- `[bluetooth]`
- `[mqtt]`
- `[home_assistant]`
- `[web]`

It must also point to a device registry file stored in TOML. Relative registry
paths are resolved relative to the config file location.

## Home Assistant Contract

The contract uses MQTT Device Discovery and a single JSON state topic per
device. The contract definition must cover:

- gateway status topic
- per-device state topic
- per-device discovery topic
- expected entities for gateway status
- expected entities for battery monitor devices

The same contract must be documented in `home-assistant/` and surfaced by the
Python CLI so docs and code do not drift immediately.

## Raspberry Pi Setup Scope

The manual guide must explain:

- Raspberry Pi OS prerequisites
- Bluetooth and package dependencies
- Python environment setup
- CLI install and validation commands
- filesystem layout expectations
- where future systemd and Ansible assets will live

## Acceptance Criteria

- The repository includes a written foundation spec and implementation plan.
- The root scaffold is committed as an initial Git commit.
- The Python CLI provides real validation and contract inspection commands.
- Example gateway and device configuration files exist and validate.
- `home-assistant/` contains a documented MQTT contract.
- `rpi-setup/` contains a manual setup guide.
- `make lint` and `make test` pass.
