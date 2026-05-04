# Raspberry Pi mDNS Hostname Recovery

## Scope

Use this runbook when the Raspberry Pi is reachable by IP or SSH, but the
expected Bonjour or mDNS hostname such as `bmgateway.local` does not resolve
correctly after moving the SD card to different hardware.

Typical symptoms:

- `ssh admin@192.168.1.x` works, but `ssh admin@bmgateway.local` does not
- Avahi advertises `bmgateway-2.local` instead of `bmgateway.local`
- the host previously lived in another Raspberry Pi with the same hostname

## Before You Start

If you just moved the SD card, make sure the old Raspberry Pi is powered off or
disconnected from the network first. Avahi will keep adding `-2`, `-3`, and so
on while another device is still advertising the same hostname.

## Copy-Paste Recovery

Run this exact block on the Raspberry Pi over SSH:

```bash
set -eu
hostnamectl
sudo systemctl enable avahi-daemon.service
sudo systemctl restart avahi-daemon.service
sudo journalctl -u avahi-daemon -n 40 --no-pager | grep -E 'Host name is|Host name conflict' || true
systemctl is-active avahi-daemon.service
```

Expected outcome:

- `avahi-daemon.service` is `active`
- the journal ends with `Host name is bmgateway.local`
- there is no fresh `Host name conflict` line after the restart

## If It Still Advertises `-2`

That means another device is still claiming the same hostname on the LAN.

1. Power off or disconnect the old Raspberry Pi or any duplicate host.
2. Run the same recovery block again.
3. Verify the last Avahi line now reports the plain hostname, for example
   `bmgateway.local`.

## Optional macOS Verification

After the Raspberry Pi reports the correct hostname, you can refresh Bonjour on
the Mac and test resolution again:

```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
ping bmgateway.local
```
