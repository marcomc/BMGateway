# USB-OTG Image Export Hardware Test

## Summary

This note captures the first hardware test for presenting a Raspberry Pi Zero
2 W as a USB mass-storage device to a Samsung `SPF-71E` digital photo frame.

The first goal was to prove the hardware path and image compatibility:

- enable USB gadget peripheral mode on the Pi
- expose a FAT32 read-only backing image through USB mass storage
- populate it with Samsung `SPF-71E` test images
- verify which image formats the frame displays

## Samsung SPF-71E Constraints

The Samsung support/manual sources for `SPF-71E` identify:

- panel size: 7 inch
- native resolution: `480 x 234`
- supported photo format: JPEG
- unsupported JPEG variants: progressive JPEG and CMYK JPEG
- external media path: USB memory or SD card

Reference sources:

- [Samsung SPF-71E support page](https://www.samsung.com/latin_en/support/model/LP07TILSST/EN/)
- [Samsung SPF-71E manual/spec mirror](https://www.manua.ls/samsung/spf-71e/manual)
- [ManualsLib SPF-71E specification page](https://www.manualslib.com/manual/792126/Samsung-Spf-71e.html?page=4)

## Test Assets

Generate local test assets with:

```bash
./scripts/generate-spf71e-test-images.sh \
  --output-dir output/spf71e-test-images
```

The generated set includes:

- native-size baseline JPEG files expected to work
- a larger same-aspect baseline JPEG
- a progressive JPEG negative control
- PNG and BMP negative controls

The expected best candidates are:

- `01_baseline_480x234_q92.jpg`
- `02_baseline_480x234_q75.jpg`

## Pi Gadget Test

The Pi-side test helper is:

```bash
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh setup \
  --source-dir /home/<user>/BMGateway-dev/output/spf71e-test-images
```

The helper creates:

- `/var/lib/bm-gateway/usb-otg/spf71e-test.img`
- a FAT32 filesystem labeled `BMGWTEST`
- a configfs USB gadget named `bmgw_spf71e`
- a read-only USB mass-storage LUN backed by the image

Status and teardown:

```bash
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh refresh
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh status
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh teardown
```

`refresh` detaches and reattaches the existing backing image without
regenerating files. Use it when a picture frame does not recognize the drive
or needs USB re-enumeration after the image was already created.

## Boot Configuration

The Raspberry Pi Zero 2 W must expose a USB device controller. For this test,
`/boot/firmware/config.txt` needs the `dwc2` overlay under `[all]`:

```text
[all]
dtoverlay=dwc2,dr_mode=peripheral
```

If this line is placed under a model-specific section that does not match the
Zero 2 W, `/sys/class/udc` remains empty and the gadget cannot attach.

## Production Export Flow

The production feature now builds on the same gadget path:

- `BMGateway` renders frame-sized bitmap files from the latest gateway snapshot
  and retained history.
- The exported drive stays read-only from the attached frame's point of view.
- Each export rebuilds the FAT backing disk image, detaches any existing gadget,
  copies the generated files, and reattaches the gadget.
- The default cadence is the gateway polling interval. A custom refresh interval
  can be set, but the Settings page warns when it is shorter than the gateway
  polling interval.
- The non-editing Settings Actions panel includes a manual
  `Export Frame Images` action for hardware validation.
- The same Actions panel includes `Refresh USB OTG Drive`, which detaches and
  reattaches the existing backing image without rendering new files.
- The Settings header includes `Diagnostics`. Its `Frame Preview` section
  embeds hidden screenshot-ready render routes such as `/frame/fleet-trend` and
  `/frame/battery-overview?page=1` inside a simulated picture-frame viewport.

## Chromium Screenshot Notes

The exporter uses Chromium screenshots rather than an ImageMagick-only drawing
path so the frame images can reuse the same HTML, CSS, chart script, colors,
and typography as the web UI. This decision was made after the generated
ImageMagick charts worked functionally on the Samsung frame but did not match
the application visuals closely enough.

On the Raspberry Pi test host, Chromium `147.0.7727.101` showed an important
headless sizing behavior: `--window-size` controls the outer browser window,
not the JavaScript viewport available to the page. With
`--window-size=480,234`, Chromium produced a `480 x 234` screenshot, but the
page reported only `innerHeight = 147`. The lower part of both a minimal test
page and the frame-render pages was therefore left black. With
`--window-size=480,321`, the page reported `innerHeight = 234` and rendered the
full target frame.

The measured difference was consistently `87` pixels on the Pi across tested
sizes, including larger windows. The export code therefore requests a Chromium
window height of:

```text
target frame height + 87 pixels
```

and then crops the top-left `target width x target height` rectangle before
saving the configured output format. The crop is not intended to add hidden
content to the generated picture. It compensates for Chromium's outer-window
inset so the page viewport itself matches the configured picture-frame size.
This is especially important for future higher-resolution frames: rendering at
the exact configured `--window-size` would still lose the bottom `87` pixels of
the page viewport on this Chromium/Pi path.

The Fleet Trend header also needs enough vertical room inside the frame image.
The title uses very small bold text, and Chromium rasterization made it look
clipped when the header was too close to the top of the image. The header is
therefore placed a few pixels lower than the absolute edge, and the chart starts
below it, while the chart surface still fills the remaining frame area.

## Application Setting

`BMGateway` now includes a disabled-by-default `[usb_otg]` config section:

```toml
[usb_otg]
enabled = false
image_path = "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img"
size_mb = 64
gadget_name = "bmgw_frame"
image_width_px = 480
image_height_px = 234
image_format = "jpeg"
appearance = "light"
refresh_interval_seconds = 0
overview_devices_per_image = 3
export_battery_overview = true
export_fleet_trend = true
fleet_trend_metrics = ["soc"]
fleet_trend_range = "7"
fleet_trend_device_ids = []
```

The Settings page exposes this as `USB OTG Image Export`. It checks whether
the required helper command and `mkfs.vfat` are installed, and whether Linux
currently exposes a USB gadget device controller under `/sys/class/udc`. If
the helper package path is missing, the page shows a red warning explaining
that the Raspberry Pi installer must be run without `--skip-usb-otg-tools`.
If the feature is enabled but no controller is detected, the page shows a red
warning explaining that the export cannot attach a gadget until the Zero USB
Plug or OTG cable and `dwc2` peripheral mode are available.

The Settings page also exposes one explicit host-preparation action at a time:

- `Prepare USB OTG Mode`
- `Restore USB Host Mode`

The page shows prepare when USB OTG peripheral mode is not prepared, and restore
when it is. These actions are separate from the export checkbox because they
edit Raspberry Pi boot configuration and require a reboot before taking effect.
The prepare action installs a BMGateway-managed
`dtoverlay=dwc2,dr_mode=peripheral` block under `[all]` in
`/boot/firmware/config.txt`. BMGateway intentionally owns this boot-mode
setting: prepare preserves existing non-peripheral `dwc2` lines, while restore
removes the managed block and any `[all]` `dtoverlay=dwc2...dr_mode=peripheral`
line so disabling the setting returns the host to USB host mode even when a
peripheral overlay predated BMGateway.

Both actions create timestamped backups beside the boot config before writing.

The bootstrap and service installers install USB OTG support by default:

- `dosfstools`, which provides `mkfs.vfat`
- `libjpeg-dev`, `python3-dev`, and `zlib1g-dev`, which allow the `pillow`
  USB OTG image renderer dependency to build on 32-bit Raspberry Pi Python
  versions when a wheel is unavailable
- `/usr/local/bin/bm-gateway-usb-otg-boot-mode`
- `/usr/local/bin/bm-gateway-usb-otg-frame-test`
- scoped sudoers entries for boot-mode prepare/restore and drive export

When the drive helper is launched through `sudo`, it only copies top-level
readable files owned by the original sudo caller into the backing image. This
keeps the web service's scoped helper permission from becoming a way to copy
root-owned host files into the exported USB drive.

Installations that do not need USB OTG support can skip those packages and
helpers with:

```bash
./scripts/bootstrap-install.sh --skip-usb-otg-tools
```

Running `rpi-setup/scripts/install-service.sh --skip-usb-otg-tools` directly
also removes the installed OTG helpers and omits their sudoers entries.

## Poll And Export Cadence

Gateway polling is controlled by `gateway.poll_interval_seconds`. The shipped
default is `300` seconds; the current live gateway may choose a longer interval
such as `600` seconds for reduced Bluetooth pressure.

Image export defaults to the same cadence as gateway polling because
`usb_otg.refresh_interval_seconds = 0` means "use the poll interval". Exporting
more often than polling mostly republishes the same data and adds extra USB
gadget detach/attach churn. The Settings page warns when gateway polling is set
below `300` seconds because BM6/BM200 discovery and connection cycles can
become less reliable at aggressive intervals. It also warns when the USB OTG
export interval is shorter than the configured gateway poll interval.

## Generated Images

The current exporter writes:

- `battery-overview-01.jpg`, `battery-overview-02.jpg`, and so on, with up to
  three configured batteries per image
- `fleet-trend-soc.jpg`, `fleet-trend-voltage.jpg`, or
  `fleet-trend-temperature.jpg`, depending on the selected Fleet Trend frame
  metrics, using the selected frame devices and web UI color keys

The image size, format, light/dark appearance, enabled image types, refresh
interval, overview page density, Fleet Trend metrics, Fleet Trend history
range, and Fleet Trend device selection are editable from Settings. Backing disk
image path, disk size, and gadget name remain read-only for now because safe
changes require detach, migration, and reattach lifecycle handling.
