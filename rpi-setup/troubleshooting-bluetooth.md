# Raspberry Pi Bluetooth Recovery

## Scope

Use this runbook when the Raspberry Pi sees a Bluetooth controller, but the
gateway runtime reports no powered adapter, `hci0` stays down, or a previous
board left behind a persisted `rfkill` soft block after an SD-card move.

Typical symptoms:

- `bm-gateway.service` keeps restarting with Bluetooth recovery errors
- `bluetoothctl show` reports `Powered: no`
- the controller state is `off-blocked` or `DOWN`

## Copy-Paste Recovery

Run this exact block on the Raspberry Pi over SSH:

```bash
set -eu
sudo systemctl stop bm-gateway.service
sudo rfkill unblock bluetooth || true
sudo python3 - <<'PY'
from pathlib import Path

for rfkill_dir in Path("/sys/class/rfkill").glob("rfkill*"):
    type_path = rfkill_dir / "type"
    soft_path = rfkill_dir / "soft"
    try:
        adapter_type = type_path.read_text(encoding="utf-8").strip()
    except OSError:
        continue
    if adapter_type != "bluetooth" or not soft_path.exists():
        continue
    try:
        soft_path.write_text("0", encoding="utf-8")
    except OSError:
        continue

for state_path in Path("/var/lib/systemd/rfkill").glob("*bluetooth"):
    try:
        state_path.write_text("0", encoding="utf-8")
    except OSError:
        continue
PY
sudo systemctl restart bluetooth.service
for controller in /sys/class/bluetooth/*; do
  [ -e "${controller}" ] || continue
  sudo hciconfig "${controller##*/}" up || true
done
sudo bluetoothctl power on || true
sudo systemctl start bm-gateway.service
rfkill list || true
hciconfig -a || true
bluetoothctl show || true
systemctl --no-pager --full status bluetooth.service bm-gateway.service --lines=20
```

Expected outcome:

- Bluetooth is no longer soft-blocked
- `hciconfig -a` shows the controller as `UP RUNNING`
- `bluetoothctl show` reports `Powered: yes`
- `bm-gateway.service` returns to `active`

## If There Is No Controller To Recover

If `/sys/class/bluetooth/` is empty or `bluetoothctl list` shows nothing, this
is not a soft-block problem. Use
[hardware-audit.md](hardware-audit.md) to confirm whether the current board
actually has integrated Bluetooth or needs a supported USB adapter.
