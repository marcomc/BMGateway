# TODO

## Next Steps

- Add BM200 history retrieval and persistence instead of only current-state
  polling.
- Decide whether BM300 Pro support ships in the same runtime milestone or
  stays behind a disabled driver flag.
- Expand integration tests to cover live-mode config handling and BLE transport
  failure paths.
- Add persistent storage for historical readings instead of only the latest
  snapshot file.
- Harden the web interface beyond the current status page once live data is
  available.
- Add integration tests that exercise the example config files end-to-end.
