# Developer Notes

## Table of Contents

- [Purpose](#purpose)
- [Start Here](#start-here)
- [Core Documents](#core-documents)
- [Product-Specific Notes](#product-specific-notes)

## Purpose

This directory is the developer-facing documentation index for `BMGateway`.

If you are looking for installation or end-user setup, go back to the root
[README.md](../README.md) and choose the relevant user path instead.

## Start Here

Read these in order when you need architectural or implementation context:

1. [Architecture: Shared Core, Separate Runtime and Web Executables](architecture/2026-04-20-shared-core-separate-web-runtime-plan.md)
2. [Foundation Spec](specs/2026-04-17-foundation-spec.md)
3. [Python Component Guide](../python/README.md)
4. [BM6 / BM200 Integration Notes](2026-04-19-bm6-bm200-integration-notes.md)
5. [BM300 Pro / BM7 Integration Notes](2026-04-25-bm300-bm7-integration-notes.md)
6. [BM Protocol Research Handoff](2026-04-25-bm-protocol-research-handoff.md)
7. [Protocol Probe Tools](protocol-probe-tools.md)
8. [History Backfill Integration Proposal](architecture/2026-04-26-history-backfill-integration-proposal.md)

## Core Documents

| Topic | Document |
| --- | --- |
| Architecture boundary | [architecture/2026-04-20-shared-core-separate-web-runtime-plan.md](architecture/2026-04-20-shared-core-separate-web-runtime-plan.md) |
| History backfill integration proposal | [architecture/2026-04-26-history-backfill-integration-proposal.md](architecture/2026-04-26-history-backfill-integration-proposal.md) |
| Service account and privilege hardening proposal | [architecture/2026-04-22-service-account-and-privilege-hardening-proposal.md](architecture/2026-04-22-service-account-and-privilege-hardening-proposal.md) |
| USB-OTG image export hardware test | [architecture/2026-04-23-usb-otg-image-export-test.md](architecture/2026-04-23-usb-otg-image-export-test.md) |
| Foundation scope | [specs/2026-04-17-foundation-spec.md](specs/2026-04-17-foundation-spec.md) |
| Python package and executables | [../python/README.md](../python/README.md) |
| Web product boundary | [../web/README.md](../web/README.md) |
| Home Assistant contract | [../home-assistant/contract.md](../home-assistant/contract.md) |
| Raspberry Pi installation and operations | [../rpi-setup/manual-setup.md](../rpi-setup/manual-setup.md) |
| BLE protocol research handoff | [2026-04-25-bm-protocol-research-handoff.md](2026-04-25-bm-protocol-research-handoff.md) |
| BLE protocol probe tools | [protocol-probe-tools.md](protocol-probe-tools.md) |

## Product-Specific Notes

- Verified BM6/BM200 protocol observations:
  [2026-04-19-bm6-bm200-integration-notes.md](2026-04-19-bm6-bm200-integration-notes.md)
- Verified BM300 Pro/BM7 live-polling protocol observations:
  [2026-04-25-bm300-bm7-integration-notes.md](2026-04-25-bm300-bm7-integration-notes.md)
- Current BM200/BM6 and BM300 Pro/BM7 protocol handoff:
  [2026-04-25-bm-protocol-research-handoff.md](2026-04-25-bm-protocol-research-handoff.md)
- Bounded BLE protocol probe tool usage:
  [protocol-probe-tools.md](protocol-probe-tools.md)
- Archive-history backfill strategy for reconnect and periodic import:
  [architecture/2026-04-26-history-backfill-integration-proposal.md](architecture/2026-04-26-history-backfill-integration-proposal.md)
- Raspberry Pi 3B operating-system and web-surface research:
  [research/2026-04-17-pi3b-web-and-os-research.md](research/2026-04-17-pi3b-web-and-os-research.md)

The `superpowers/` documents in this directory are implementation planning
artifacts, not end-user documentation. Use them only when you need historical
developer context.
