# TODO

## Next Steps

- Complete live BM200 history retrieval and persist decoded history packets
  instead of only current-state polling.
- Decide whether BM300 Pro support ships in the same runtime milestone or
  stays behind a disabled driver flag.
- Add yearly degradation summaries on top of the daily and monthly rollups.
- Add MQTT availability/error semantics beyond the current state payload fields.
- Expand integration tests to cover live-mode config handling and BLE transport
  failure paths.
- Grow the web interface beyond the current config, contract, storage, and
  history views.
- Add integration tests that exercise the example config files end-to-end.
- Revisit Docker only for 64-bit deployment targets if containerization becomes
  operationally useful again.
