# Shared Core, Separate Runtime and Web Executables

## Summary

`BMGateway` should remain one repository and one shared Python codebase, but it
should present two operational applications:

- `bm-gateway` for the runtime, CLI inspection, and Home Assistant publishing
- `bm-gateway-web` for the optional local web interface

This keeps code reuse high while restoring a clear product boundary.

## Decision

Adopt a shared-core architecture with separate executables, not separate
products and not duplicated codebases.

The existing runtime, config, registry, persistence, contract, and BLE logic
remain shared in `python/src/bm_gateway/`.

The web interface remains server-rendered Python, but it becomes a first-class
optional executable and service instead of only a subcommand hanging off the
main CLI.

## Goals

- Preserve the existing working runtime and Home Assistant behavior.
- Keep the web interface optional at install and runtime.
- Avoid code duplication between runtime and web surfaces.
- Keep backward compatibility for existing `bm-gateway web ...` usage during
  the migration.
- Make the repository documentation clearer and less repetitive.

## Non-Goals

- Rewriting the web UI into a separate frontend stack.
- Splitting the repository into multiple packages or repositories.
- Changing the default web bind from `0.0.0.0`.
- Adding authentication in this slice.

## Target Architecture

| Layer | Responsibility |
| --- | --- |
| Shared core | Config loading, device registry, BLE drivers, runtime snapshots, SQLite persistence, MQTT publishing, Home Assistant contract, archive sync |
| Runtime executable | `bm-gateway` for `config`, `devices`, `ha`, `history`, and `run` |
| Web executable | `bm-gateway-web` for the optional management UI and snapshot rendering |
| Compatibility layer | Keep `bm-gateway web render`, `bm-gateway web serve`, and `bm-gateway web manage` working while the dedicated web executable becomes the primary interface |

## Repository Boundaries

| Path | Role |
| --- | --- |
| `python/src/bm_gateway/` | Authoritative implementation for shared core, runtime CLI, and web executable |
| `web/` | Web product notes and boundary documentation, not a second source tree |
| `home-assistant/` | MQTT contract and Home Assistant-facing assets |
| `rpi-setup/` | Raspberry Pi install, service, and operational guidance |
| `docs/` | Cross-cutting architecture, research, and migration decisions |

## Deployment Model

The supported appliance shape stays:

- one runtime `systemd` service for collection and publishing
- one optional web `systemd` service for the management UI

The web service remains optional and disabled with `--disable-web`.

The default web bind remains `0.0.0.0` because local-network access is an
explicit project goal. Security hardening stays a separate follow-up topic.

## Security Notes

Current posture:

- the web service increases the exposed attack surface
- the runtime-only appliance is smaller and safer
- separating executables improves operational control, but does not by itself
  add authentication or transport security

Immediate security value from this architecture:

- web can be installed and run independently from the runtime
- the runtime appliance remains fully usable without the web service
- operators can disable one port and one service cleanly when they only need
  CLI plus Home Assistant

Deferred security work:

- authentication for the web UI
- optional reverse-proxy or VPN guidance
- stricter host firewall recommendations
- CSRF and request-origin review for mutating routes

## Documentation Standard

Documentation should follow a single-source-of-truth rule:

- root `README.md`: overview, quick start, repo map, and links
- `docs/README.md`: central documentation index
- component `README.md` files: contributor-oriented entry pages for their area
- detailed setup, contract, and architecture content lives in one canonical
  document and is linked elsewhere instead of copied

## Migration Plan

### Phase 1: Establish the boundary

- add this architecture document
- add a dedicated `bm-gateway-web` executable
- keep `bm-gateway web ...` as a compatibility alias
- update service units and install flows to use the dedicated web executable

### Phase 2: Clarify packaging and operations

- link or install both executables in standalone and dev installs
- document `bm-gateway` as the runtime CLI
- document `bm-gateway-web` as the optional UI process

### Phase 3: Reduce documentation duplication

- trim the root `README.md` to overview and entry-point links
- promote `docs/README.md` to the central index
- keep component-specific details in `python/`, `home-assistant/`, and
  `rpi-setup/`

### Phase 4: Remove stale artifacts

- delete obsolete prototype or scaffold directories that are no longer part of
  the shipped architecture
- keep only files that support the live Python-hosted product

## Acceptance Criteria

- `bm-gateway-web` exists as a dedicated installed executable
- `bm-gateway web manage` still works
- service installation uses `bm-gateway-web` for the web unit
- root and component docs no longer duplicate the same installation narrative
- obsolete scaffold material is removed
- `make check` passes

## Rollback Safety

This migration is intentionally compatibility-first:

- the main package name stays `bm-gateway`
- `python -m bm_gateway` stays supported
- the old web subcommands remain valid during the transition
- runtime data formats and config file structure stay unchanged
