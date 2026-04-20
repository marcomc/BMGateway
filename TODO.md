# TODO

## Next Steps

- Complete live BM200 history retrieval and persist decoded history packets
  instead of only current-state polling.
- Decide whether BM300 Pro support ships in the same runtime milestone or
  stays behind a disabled driver flag.
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

- [ ] Redesign the battery overview grid for scalable multi-device layouts.
  The landing page should optimize the visible device tiles for screen size and
  device count while always preserving a visible add-device affordance.
  Actions:
  - define responsive layout rules for small, medium, and large screens so the
    overview uses rows and columns efficiently
  - reserve one tile-sized affordance for adding a new device when the visible
    device count is below the configured page capacity
  - decide the maximum number of visible devices per overview page before
    scrolling is required
  - add a display setting that controls the visible-device limit for the
    battery overview
  - implement horizontal navigation for larger fleets, including touch scroll
    and explicit arrow controls for pointer devices
  - ensure the layout remains visually balanced for one, two, three, four, and
    many-device scenarios

- [ ] Audit and extend fleet trend range handling.
  The longer time-range controls on the fleet trend widget may be failing
  silently or may simply lack data. That ambiguity needs to be resolved, and
  the control set should include an `All` range.
  Actions:
  - verify whether `30 days`, `90 days`, `1 year`, and `2 years` fail because
    of missing data or because of a chart-range bug
  - add explicit empty-state messaging when a selected range has no usable data
  - fix any range-selection or data-window logic that prevents valid long-range
    data from rendering
  - add an `All` range that shows the full retained history, regardless of the
    number of years available
  - add regression coverage for short, long, and all-history range selection

- [ ] Improve history-page device selection and navigation clarity.
  The history view should make it obvious how to switch between monitored
  batteries instead of appearing locked to a single device.
  Actions:
  - verify the current behavior when more than one configured battery exists
  - if device switching is missing or unclear, add an explicit device selector
    at the top of the history page
  - choose a selector pattern that scales to larger fleets, such as pills,
    segmented buttons, or a compact dropdown plus quick navigation
  - ensure that switching devices updates all history charts, summaries, and
    tables consistently
  - add regression coverage for multi-device history navigation
