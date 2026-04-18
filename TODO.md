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
- Grow the web interface beyond the current config, contract, storage,
  analytics, and history views.
- Add integration tests that exercise the example config files end-to-end.
- Revisit Docker only for 64-bit deployment targets if containerization becomes
  operationally useful again.
