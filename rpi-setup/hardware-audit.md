# Raspberry Pi Hardware Audit and Service Tuning

## Scope

This runbook captures the manual audit flow for a Raspberry Pi gateway host
 before deploying `BMGateway`.

Use it to:

- confirm the board model before assuming integrated radios exist
- verify whether Wi-Fi and Bluetooth hardware are actually present
- confirm Ethernet and Wi-Fi routing priority
- review boot delays, memory pressure, and running services
- identify conservative disable candidates for a headless appliance

This document is written to be reusable as future automation input for
Ansible or other provisioning systems.

## Hardware Validation First

Do not assume that every Raspberry Pi has integrated Wi-Fi or Bluetooth.

Run:

```bash
hostnamectl
cat /proc/device-tree/model
uname -m
grep -E '^(Hardware|Revision|Model|Serial)' /proc/cpuinfo
lsusb
ip -br link
ls -l /sys/class/net
ls -l /sys/class/bluetooth
```

Interpretation:

- Raspberry Pi `3B`, `3B+`, `Zero W`, `Zero 2 W`, `4`, `400`, and `5` include
  integrated Wi-Fi and Bluetooth.
- plain Raspberry Pi `Zero` without the `W` does not include integrated
  Wi-Fi or Bluetooth.
- Raspberry Pi `Model B Rev 2` does not include integrated Wi-Fi or Bluetooth.
- If `ip -br link` shows only `lo` and `eth0`, there is no usable Wi-Fi
  network interface.
- If `/sys/class/bluetooth` is empty, there is no usable Bluetooth controller
  exposed to the kernel.
- If `lsusb` shows only the LAN9512/LAN9514 hub and Ethernet controller on an
  older board, there is no USB Wi-Fi or Bluetooth dongle attached either.

## Example Failure Mode: Old Model B Board

One audited host identified itself as:

```text
Raspberry Pi Model B Rev 2
Linux 6.12.75+rpt-rpi-v6
```

Observed facts:

- no `wlan0` device was present
- `/sys/class/bluetooth` was empty
- `lsusb` showed only:
  - Linux root hub
  - Microchip/SMSC hub
  - Microchip/SMSC Fast Ethernet adapter

Conclusion:

- Wi-Fi was not failing because of a bad SSID or driver issue
- Wi-Fi was not present as hardware on that board
- Bluetooth was not present as hardware on that board

If you need Wi-Fi and Bluetooth for `BMGateway`, use a real Raspberry Pi `3B`
or newer wireless-capable model, or add supported USB adapters.

The currently used gateway hardware in this project is an older Raspberry Pi
`Model B Rev 2`, so USB Wi-Fi and USB Bluetooth adapters are expected.

## Network Audit

Check current links and routes:

```bash
ip -br addr
ip route
nmcli general status
nmcli device status
nmcli -t -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT connection show
nmcli -t -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT connection show --active
```

What to look for:

- `eth0` should be `connected` when the cable is plugged in
- `wlan0` should exist only if Wi-Fi hardware or a Wi-Fi dongle is present
- the default route should point to `eth0` when Ethernet is active
- a saved Wi-Fi profile without a `wlan0` device means the configuration
  exists, but the hardware does not

## Optional: Make `admin` Passwordless for `sudo`

For repeated audit and provisioning work, you may want a non-interactive sudo
path for the `admin` account. Use a sudoers drop-in and validate it
immediately:

```bash
printf 'admin ALL=(ALL) NOPASSWD:ALL\n' | sudo tee /etc/sudoers.d/10-admin-nopasswd >/dev/null && sudo chmod 440 /etc/sudoers.d/10-admin-nopasswd && sudo visudo -cf /etc/sudoers.d/10-admin-nopasswd
```

## Ethernet Priority Over Wi-Fi

When both interfaces exist, keep Ethernet preferred and let Wi-Fi take over
only when Ethernet is unavailable.

With NetworkManager:

```bash
sudo nmcli connection modify netplan-eth0 ipv4.route-metric 100 ipv6.route-metric 100
sudo nmcli connection modify <wifi-connection-name> ipv4.route-metric 600 ipv6.route-metric 600
sudo nmcli connection modify netplan-eth0 connection.autoconnect-priority 100
sudo nmcli connection modify <wifi-connection-name> connection.autoconnect-priority 10
sudo nmcli connection up netplan-eth0
sudo nmcli connection up <wifi-connection-name>
```

Interpretation:

- lower route metric wins
- higher autoconnect priority wins when both profiles are eligible
- Ethernet remains the primary path while the cable is present
- Wi-Fi becomes the default path when Ethernet drops and the Wi-Fi profile can
  connect

Do not apply these commands on a host with no Wi-Fi hardware; they are only for
boards or adapters that actually expose `wlan0`.

## Wi-Fi and Bluetooth Verification on Wireless-Capable Boards

On a true wireless-capable Raspberry Pi or a Pi with USB radios attached, run:

```bash
sudo apt update
sudo apt install -y iw rfkill bluez

ip -br link
iw dev
rfkill list
bluetoothctl list
journalctl -b -u NetworkManager -u wpa_supplicant -u bluetooth --no-pager | tail -n 200
```

Expected outcomes:

- `iw dev` lists `wlan0`
- `rfkill list` shows Wi-Fi and Bluetooth blocks, if any
- `bluetoothctl list` shows an HCI controller
- the journal shows device discovery instead of only generic service startup

## Performance and Boot Audit

Use:

```bash
free -h
df -h / /boot /var/log
uptime
ps -eo pid,comm,%cpu,%mem --sort=-%cpu | sed -n '1,20p'
ps -eo pid,comm,%cpu,%mem --sort=-%mem | sed -n '1,20p'
systemd-analyze
systemd-analyze blame --no-pager | sed -n '1,60p'
systemd-analyze critical-chain --no-pager | sed -n '1,80p'
systemctl --type=service --state=running --no-pager --no-legend
systemctl list-unit-files --type=service --state=enabled,disabled,masked,static --no-pager
```

Typical headless-gateway concerns:

- cloud-init stages taking minutes after first boot
- `NetworkManager-wait-online.service` delaying `multi-user.target`
- unneeded removable-media or radio services remaining enabled on an appliance
- audio, video, and camera modules consuming memory on a box that will never
  use them

## Keep Enabled

These services should normally remain enabled on a `BMGateway` appliance:

- `ssh.service`
  - required for remote administration
- `NetworkManager.service`
  - preferred network control plane for this project
- `avahi-daemon.service`
  - keeps `.local` name resolution such as `bmgateway.local`
- `systemd-timesyncd.service`
  - keeps clock drift under control for logs, SQLite timestamps, and Home
    Assistant data quality
- `dbus.service`
  - required by NetworkManager and other system services
- `systemd-journald.service`
  - required for diagnostics
- `systemd-udevd.service`
  - required for device discovery and hotplug

Usually keep unless you have a specific reason to remove them:

- `polkit.service`
  - useful for controlled NetworkManager operations
- `cron.service`
  - useful for housekeeping jobs if later needed
- `getty@tty1.service`
  - useful for local recovery on a connected monitor/keyboard

## Good Disable Candidates for a Headless Gateway

These are conservative candidates to disable once the appliance is stable.

### Safe to Disable on a Non-Wireless Board

- `bluetooth.service`
  - no Bluetooth controller exists on an old `Model B Rev 2`
- `wpa_supplicant.service`
  - no Wi-Fi device exists on an old `Model B Rev 2`

Commands:

```bash
sudo systemctl disable --now bluetooth.service
sudo systemctl disable --now wpa_supplicant.service
```

### Usually Safe to Disable on a Headless Appliance

- `NetworkManager-wait-online.service`
  - reduces boot delay; useful only when another service strictly requires the
    network to be fully up before startup
- `udisks2.service`
  - not needed on a fixed-storage headless appliance
- `serial-getty@ttyAMA0.service`
  - disable if serial console is not part of your recovery workflow
- `getty@tty1.service`
  - optional to disable if the appliance is fully headless and remote-only

Commands:

```bash
sudo systemctl disable --now NetworkManager-wait-online.service
sudo systemctl disable --now udisks2.service
sudo systemctl disable --now serial-getty@ttyAMA0.service
```

Optional:

```bash
sudo systemctl disable --now getty@tty1.service
```

### Disable After Initial Provisioning

If you are not using cloud-init after first boot, disable it after the machine
has reached its stable desired state:

- `cloud-init-local.service`
- `cloud-init-main.service`
- `cloud-init-network.service`
- `cloud-config.service`
- `cloud-final.service`

Commands:

```bash
sudo cloud-init status
sudo touch /etc/cloud/cloud-init.disabled
sudo systemctl disable cloud-init-local.service cloud-init-main.service cloud-init-network.service cloud-config.service cloud-final.service
```

Note:

- do this only after confirming you no longer depend on cloud-init for future
  boot configuration

## Optional Kernel Module Reductions

These were present on one audited headless box and are not required for
`BMGateway` itself:

- audio:
  - `snd_bcm2835`
  - `snd_soc_hdmi_codec`
- local graphics and DRM:
  - `vc4`
  - `drm`
  - `drm_kms_helper`
  - `drm_display_helper`
- camera and video stack:
  - `bcm2835_codec`
  - `bcm2835_v4l2`
  - `bcm2835_isp`
  - `bcm2835_mmal_vchiq`

Only disable these if the appliance is truly headless and will never need:

- HDMI console output
- local audio
- Raspberry Pi camera
- hardware video acceleration

This should be implemented carefully through `/boot/firmware/config.txt` and
`/etc/modprobe.d/*.conf`, then retested after reboot.

Do not disable them blindly if you still rely on a local display for recovery.

## Recommended Hardware for This Project

Current audited deployment hardware:

- Raspberry Pi `Model B Rev 2`
- USB Wi-Fi dongle
- USB Bluetooth dongle

Preferred integrated-radio alternatives:

- Raspberry Pi `3B`
- Raspberry Pi `3B+`
- Raspberry Pi `Zero W`
- Raspberry Pi `Zero 2 W`
- Raspberry Pi `4`
- Raspberry Pi `400`
- Raspberry Pi `5`

If you keep using an older non-wireless Pi:

- add a supported USB Wi-Fi adapter for `wlan0`
- add a supported USB Bluetooth adapter for BLE work

Without those radios, this host can still run the `BMGateway` CLI, MQTT
publishing, SQLite storage, and web UI over Ethernet only.
