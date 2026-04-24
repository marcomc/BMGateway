# Service Account And Privilege Hardening Proposal

## Table of Contents

- [Summary](#summary)
- [Current State](#current-state)
- [Observed Permission Inventory](#observed-permission-inventory)
- [Security Risks In The Current Shape](#security-risks-in-the-current-shape)
- [Recommended Target Model](#recommended-target-model)
- [Sudo And Host-Control Design Options](#sudo-and-host-control-design-options)
- [Systemd Hardening Changes](#systemd-hardening-changes)
- [Recommended Implementation Phases](#recommended-implementation-phases)
- [Open Questions](#open-questions)

## Summary

This document captures the April 22, 2026 investigation into how
`BMGateway` currently executes privileged operations and what a safer
least-privilege deployment model should look like.

The short conclusion is:

- the application should run as a dedicated non-login service account such as
  `bm-gateway`
- the long-running runtime and web processes should stay unprivileged
- only true host-admin actions should cross a privileged boundary
- the current direct `sudo -n systemctl ...` model should be narrowed or
  replaced with a smaller root-owned control surface
- web authentication and request-hardening remain critical because the current
  web UI exposes mutating routes without auth

## Current State

The current installer and service setup are tied to the invoking user rather
than to a dedicated service account.

- `make install` installs the runtime in `~/.local/share/bm-gateway/venv` and
  links the executables into `~/.local/bin/`
- `rpi-setup/scripts/install-service.sh` defaults the service account to the
  current `sudo` user or current user
- the generated `systemd` units run as that chosen user and use the same
  user's `~/.local/bin` and `~/.config/bm-gateway/` paths

Relevant sources:

- [../../Makefile](../../Makefile)
- [../../scripts/bootstrap-install.sh](../../scripts/bootstrap-install.sh)
- [../../rpi-setup/scripts/install-service.sh](../../rpi-setup/scripts/install-service.sh)

## Observed Permission Inventory

### Operations That Already Work As An Unprivileged User

The codebase already performs most application work without root:

- BLE polling uses `Bleak` over BlueZ D-Bus on Linux
- adapter recovery uses `bluetoothctl` without `sudo`
- config edits write the configured TOML files
- device edits write the device registry TOML file
- snapshot persistence and history pruning operate on the local SQLite database
- `run once` from the web UI invokes the CLI as the same user
- archive-history sync uses the same BLE/runtime path and local database

Primary code paths:

- [../../python/src/bm_gateway/runtime.py](../../python/src/bm_gateway/runtime.py)
- [../../python/src/bm_gateway/web.py](../../python/src/bm_gateway/web.py)
- [../../python/src/bm_gateway/web_actions.py](../../python/src/bm_gateway/web_actions.py)
- [../../python/src/bm_gateway/cli.py](../../python/src/bm_gateway/cli.py)
- [../../python/src/bm_gateway/archive_sync.py](../../python/src/bm_gateway/archive_sync.py)
- [../../python/src/bm_gateway/state_store.py](../../python/src/bm_gateway/state_store.py)

### Operations That Currently Cross A Privileged Boundary

The current application code uses `sudo -n` only for these host-admin actions:

- restart `bm-gateway.service`
- restart `bluetooth.service`
- reboot the host with `systemctl reboot`

Primary code paths:

- [../../python/src/bm_gateway/web_actions.py](../../python/src/bm_gateway/web_actions.py)
- [../../python/src/bm_gateway/web.py](../../python/src/bm_gateway/web.py)

### Current Web Service Capabilities

The generated web service currently grants:

- `CAP_NET_BIND_SERVICE`
- `CAP_SETUID`
- `CAP_SETGID`
- `CAP_AUDIT_WRITE`

Only `CAP_NET_BIND_SERVICE` is clearly justified by the current design, and
only when binding the web UI to a privileged port such as `80`.

Relevant sources:

- [../../rpi-setup/systemd/bm-gateway-web.service](../../rpi-setup/systemd/bm-gateway-web.service)
- [../../rpi-setup/scripts/install-service.sh](../../rpi-setup/scripts/install-service.sh)

## Security Risks In The Current Shape

### Human-User Service Identity

Running the service as `admin`, `pi`, or another interactive user weakens
separation between appliance runtime state and operator identity. It also makes
future sudo policy harder to reason about because the service and the operator
share the same account.

### Broad Optional Sudo Guidance

The repository docs currently include optional guidance for
`admin ALL=(ALL) NOPASSWD:ALL`. That is broader than the application needs and
would turn compromise of the service user into broad root-level host control.

Relevant source:

- [../../rpi-setup/manual-setup.md](../../rpi-setup/manual-setup.md)

### Web Exposure

The current web UI:

- binds to `0.0.0.0` by default
- does not implement authentication
- exposes mutating POST routes that edit config, device state, history, and
  host actions

This means privilege hardening for the service account is necessary but not
sufficient. Network exposure and web-surface controls remain part of the same
security problem.

Relevant sources:

- [2026-04-20-shared-core-separate-web-runtime-plan.md](2026-04-20-shared-core-separate-web-runtime-plan.md)
- [../../python/src/bm_gateway/config.py](../../python/src/bm_gateway/config.py)
- [../../python/src/bm_gateway/web.py](../../python/src/bm_gateway/web.py)

## Recommended Target Model

The recommended target model is:

1. Create a dedicated non-login system account, for example `bm-gateway`.
2. Run both `bm-gateway.service` and `bm-gateway-web.service` as that account.
3. Move installed runtime assets away from user-home locations and into stable
   system-managed paths.
4. Keep the long-running application unprivileged.
5. Allow only the exact host-admin operations that the product deliberately
   exposes.

Recommended ownership layout:

| Path | Suggested owner | Notes |
| --- | --- | --- |
| `/etc/bm-gateway/` | `root:bm-gateway` or `bm-gateway:bm-gateway` | Depends on whether live web editing of config remains allowed |
| `/var/lib/bm-gateway/` | `bm-gateway:bm-gateway` | Runtime state, SQLite DB, snapshots |
| `/usr/local/bin/bm-gateway` | `root:root` | Stable executable path |
| `/usr/local/bin/bm-gateway-web` | `root:root` | Stable executable path |

### Why A Dedicated User Is A Good Idea

Yes, a dedicated user is the right direction here.

It improves:

- process identity separation
- file ownership clarity
- auditability of sudo or helper policy
- future `systemd` hardening
- the ability to reason about what the application can and cannot change

It does not, by itself, solve:

- unauthenticated web access
- CSRF/request-origin concerns
- overbroad privileged helper design

## Sudo And Host-Control Design Options

### Interim Option: Exact `sudoers` Rule

If the current `sudo -n systemctl ...` code path is kept temporarily, the
service account should get access only to the exact required commands.

Example:

```sudoers
User_Alias BMGW = bm-gateway
Cmnd_Alias BMGW_HOSTCTL = \
    /usr/bin/systemctl restart bm-gateway.service, \
    /usr/bin/systemctl restart bluetooth.service, \
    /usr/bin/systemctl reboot, \
    /usr/bin/systemctl poweroff

BMGW ALL=(root) NOPASSWD: BMGW_HOSTCTL
```

This is materially safer than `NOPASSWD:ALL`, but it still leaves the
application talking directly to `systemctl`.

### Preferred Option: Root-Owned Helper Or Dedicated Oneshot Units

The better design is to remove direct `sudo systemctl ...` from the
application and replace it with one of these:

- a root-owned helper that accepts only `restart-runtime`,
  `restart-bluetooth`, `reboot`, and `poweroff`
- dedicated root-owned `systemd` oneshot units that perform those actions and
  can be started by a narrower policy

Why this is better:

- the privileged API becomes smaller and easier to review
- application code no longer gets generic access to `systemctl`
- future auditing and tests can target a single boundary

### Bluetooth-Specific Note

The current code path for adapter recovery uses `bluetoothctl` directly and
does not currently require `sudo`.

That suggests the service account should first be tested with BlueZ D-Bus
access as an ordinary service user before adding any extra Bluetooth-specific
privilege. If a target distro requires group-based access, a narrow
`SupplementaryGroups=bluetooth` model is preferable to broader root privilege.

## Systemd Hardening Changes

Once the application no longer depends on in-process `sudo`, the units should
be hardened more aggressively.

Recommended defaults to evaluate:

- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `ProtectSystem=strict`
- `ProtectHome=true`
- `ProtectControlGroups=yes`
- `ProtectKernelTunables=yes`
- `ProtectKernelModules=yes`
- `LockPersonality=yes`
- `RestrictNamespaces=yes`
- `SystemCallArchitectures=native`
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`
- `ReadWritePaths=/var/lib/bm-gateway /etc/bm-gateway`

Capability changes:

- keep `CAP_NET_BIND_SERVICE` only if the web service must bind directly to
  `:80`
- drop `CAP_SETUID`
- drop `CAP_SETGID`
- drop `CAP_AUDIT_WRITE`

If the web UI moves behind a reverse proxy or to an unprivileged port such as
`8080`, `CAP_NET_BIND_SERVICE` can be removed too.

## Recommended Implementation Phases

### Phase 1: Preserve Behavior, Narrow Privilege

- add a dedicated `bm-gateway` service user
- install runtime assets into system-managed paths
- run both services as `bm-gateway`
- replace `NOPASSWD:ALL` guidance with exact command-scoped sudo guidance
- remove unnecessary web service capabilities

### Phase 2: Replace Direct `sudo` In The App

- remove direct `sudo -n systemctl ...` calls from Python
- add a narrow root-owned helper or dedicated privileged oneshot units
- update tests and docs to describe the new privileged boundary

### Phase 3: Add Web-Surface Hardening

- authentication for the web UI
- CSRF/request-origin validation for mutating routes
- clearer firewall or reverse-proxy guidance
- safer default bind policy if LAN-wide exposure remains optional

## Open Questions

- Should the web UI continue to edit live config files directly under
  `/etc/bm-gateway/`, or should config mutation also move behind a narrower
  privileged boundary?
- Should the default deployment keep direct port `80`, or should the product
  move to an unprivileged port and optional reverse proxy?
- Which Raspberry Pi OS / BlueZ combinations, if any, require explicit
  supplemental group or D-Bus policy changes for the service account?
