# TODO

## Next Steps

- Complete BM6-family onboard-history retrieval.
  The current devices advertise and poll as BM6-family monitors, but live
  archive probes do not yet answer the existing BM200 history-count/download
  commands. Finish the device-memory fetch path before treating reconnect
  backfill as shipped on real hardware.
- Complete BM300 Pro/BM7 feature parity beyond live current-state polling.
  Live voltage, SoC, temperature, RSSI, and device state now use a dedicated
  BM300 Pro driver. Onboard history, firmware version reads, cranking/charging
  event records, and rapid acceleration/deceleration persistence still need
  protocol capture or live verification before they should ship.
- Add richer degradation analytics beyond the current yearly summaries and
  rolling comparison windows.
- Add MQTT birth/LWT republish handling beyond the current availability and
  error semantics.
- Expand integration tests to cover live-mode config handling and BLE transport
  failure paths.
- Add editable gateway-safe settings forms and multi-device comparative
  filtering on top of the new premium battery/history/devices/settings UI.
- Decide the web hardening plan: authentication, firewall guidance, and whether
  LAN exposure should stay the default long term.
- Revisit whether to add a dedicated local development environment; for now,
  treat the main gateway host as the only live validation target for hobby
  development and use it carefully for production-adjacent testing.
- Add integration tests that exercise the example config files end-to-end.
- Revisit Docker only for 64-bit deployment targets if containerization becomes
  operationally useful again.

## Propositions

- [ ] Implement a dedicated `bm-gateway` service account and privilege-hardening plan.
  Rework the appliance runtime so it no longer depends on a human user account
  and so host-admin operations are exposed through a narrower privileged
  boundary.
  Reference:
  - [docs/architecture/2026-04-22-service-account-and-privilege-hardening-proposal.md](docs/architecture/2026-04-22-service-account-and-privilege-hardening-proposal.md)
  Actions:
  - add a dedicated non-login `bm-gateway` service user for runtime and web
  - move install, config, and state ownership to system-managed paths
  - replace broad sudo guidance with exact command-scoped privilege rules
  - remove unneeded `systemd` capabilities from the web unit
  - decide whether privileged host actions should use a narrow helper or
    dedicated oneshot units instead of direct `sudo systemctl ...`
  - add follow-up web hardening for authentication and mutating-route safety

- [ ] Add an explicit admin trust boundary for host-control web actions.
  The management UI currently includes mutating host-control actions such as
  reboot, shutdown, Bluetooth restart, and USB OTG prepare/export/refresh.
  These actions must not remain reachable from a broadly exposed unauthenticated
  LAN web surface.
  Actions:
  - decide whether the web UI should default to local-only binding until an
    admin boundary exists
  - add authentication or another explicit operator trust boundary for
    management routes
  - add CSRF and Origin or Referer validation for mutating POST actions
  - separate read-only status pages from privileged host-control actions
  - document the supported deployment model for LAN exposure after the boundary
    is implemented

- [ ] Add camera-based barcode scanning for device MAC or serial capture.
  Manual MAC entry is error-prone on phones and laptops. The original mobile
  app supports scanning the device barcode, and the web UI should offer the
  same shortcut when camera access is available.
  Actions:
  - add a scan action to the add-device flow next to the MAC or serial input
  - support camera access on desktop and mobile browsers when permitted
  - decode the scanned barcode and normalize the captured value into the
    expected MAC-address format used by the registry
  - keep manual entry as the fallback path when the camera is unavailable or
    the scan fails
  - define validation and error messaging for unreadable or unsupported barcode
    payloads

- [ ] Add Raspberry Pi USB-OTG image-export mode for external monitors and
  digital picture frames.
  The first implementation can present the Raspberry Pi Zero USB-OTG hardware
  path as a thumb-drive-like read-only mass-storage device and regenerate
  battery overview and Fleet Trend images. Keep this proposition open until
  the generated visuals are validated on real frames and the operational
  lifecycle is hardened.
  Actions:
  - visually validate the generated overview and Fleet Trend images against the
    real web UI on the Samsung `SPF-71E`
  - collect behavior notes for how quickly each target picture frame rescans
    the rebuilt USB drive after detach/reattach
  - decide whether a browser/screenshot renderer is needed for closer
    pixel-level parity with the web UI
  - harden failure reporting for drive-helper failures in long-running service
    logs and Settings status

- [ ] Add advanced USB OTG disk-image management settings.
  The current UI should keep backing disk image path, disk size, and gadget
  name read-only because changing them safely requires lifecycle operations.
  Actions:
  - allow advanced users to edit the backing disk image path, disk size, and
    gadget name
  - detach the USB gadget before applying disk image changes
  - create, resize, rename, or migrate the backing disk image as needed
  - reattach the USB gadget after the new disk settings are valid
  - surface clear failure states when disk migration or gadget reattach fails

- [ ] Add user-managed custom images for USB OTG frame export.
  Allow users and external systems to upload persistent custom frame images,
  such as branding slides or personal photos, and include them in the USB OTG
  drive alongside BMGateway-generated overview and Fleet Trend images without
  overwriting them during refreshes.
  Actions:
  - add a persistent Raspberry Pi storage area for uploaded USB OTG frame
    images that survives backing disk image recreation
  - add a setting to include or exclude uploaded custom images from USB OTG
    exports
  - copy enabled custom images into the OTG backing disk image on every export
    and refresh without deleting the source uploads
  - trigger a USB drive refresh automatically after a successful web or API
    upload so connected frames can discover the new image
  - add web UI controls to upload images, list stored images, remove images,
    and show compact previews in the USB OTG settings area
  - add API endpoints for uploading, listing, previewing, and deleting custom
    frame images so other devices can pipeline images into the frame drive
  - validate uploaded image type, dimensions, file size, and filename safety
    before accepting the file
  - generate and store thumbnails or previews during both web and API uploads
  - decide whether uploads should be preserved in their original format or
    normalized to the configured USB OTG export format
  - define filename conflict behavior, ordering behavior, and quota limits for
    custom images on the frame drive

- [ ] Add hardware and live resource diagnostics to the Diagnostics page.
  Extend Diagnostics with host-level observability so appliance troubleshooting
  can separate application problems from Raspberry Pi, network, storage, CPU,
  RAM, and live throughput issues.
  Actions:
  - detect whether the host is a Raspberry Pi and show the exact Raspberry Pi
    model when available
  - show processor model, CPU core count, and current CPU usage
  - show installed RAM, current RAM usage, and swap usage
  - list mounted filesystems or relevant storage mounts with capacity and usage
  - list network interfaces with link state, IP addresses, and active default
    route
  - show Wi-Fi network details when available, including SSID and signal data
  - show current network upload and download throughput by interface
  - keep data collection read-only and safe for the web service privilege model
  - add tests for parsing Raspberry Pi model, memory, CPU, storage, and network
    diagnostics from representative Linux command output

- [ ] Add optional live BLE monitoring sessions for battery monitors.
  Keep periodic Raspberry Pi polling as the default appliance behavior, but add
  an explicit user-controlled live mode that holds a BLE connection open and
  streams voltage, temperature, and other readings at roughly the cadence used
  by the original mobile app.
  Reference:
  - [docs/architecture/2026-04-24-optional-live-ble-monitoring-proposal.md](docs/architecture/2026-04-24-optional-live-ble-monitoring-proposal.md)
  Actions:
  - identify the BLE read or notification path used by the original app for
    near-real-time updates
  - add a bounded live-session service with start, stop, timeout, and
    cancellation behavior
  - expose live readings to the web UI without refreshing the whole page
  - warn users that live mode may block the original phone app or other BLE
    clients while BMGateway holds the connection
  - keep normal unattended monitoring on the slower periodic polling loop
    unless live mode is explicitly enabled
  - decide whether live samples remain transient, update latest state, or are
    downsampled before persistence and MQTT publishing
