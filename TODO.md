# TODO

## Next Steps

- Add BM200 history retrieval and persistence instead of only current-state
  polling.
- Decide whether BM300 Pro support ships in the same runtime milestone or
  stays behind a disabled driver flag.
- Add monthly and yearly degradation summaries on top of the daily rollups.
- Add MQTT availability/error semantics beyond the current state payload fields.
- Expand integration tests to cover live-mode config handling and BLE transport
  failure paths.
- Harden the web interface beyond the current management and history views.
- Add integration tests that exercise the example config files end-to-end.
- Revisit Docker only for 64-bit deployment targets if containerization becomes
  operationally useful again.
