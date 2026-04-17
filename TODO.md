# TODO

## Next Steps

- Implement the Bluetooth polling runtime behind the documented MQTT contract.
- Replace the fake-reader runtime with BM200 Bluetooth transport and parsing.
- Decide whether BM300 Pro support ships in the same runtime milestone or
  stays behind a disabled driver flag.
- Expand integration tests to cover the example config files, discovery export,
  and runtime snapshot generation end-to-end.
- Add persistent storage for historical readings instead of only the latest
  snapshot file.
- Harden the web interface beyond the current status page once live data is
  available.
- Add integration tests that exercise the example config files end-to-end.
