# USB-OTG Image Export Hardware Test

## Summary

This note captures the first hardware test for presenting a Raspberry Pi Zero
2 W as a USB mass-storage device to a Samsung `SPF-71E` digital photo frame.

The goal of this slice is not the full automated `BMGateway` image-export
runtime. The goal is to prove the hardware path and image compatibility first:

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
  --source-dir /home/admin/BMGateway-dev/output/spf71e-test-images
```

The helper creates:

- `/var/lib/bm-gateway/usb-otg/spf71e-test.img`
- a FAT32 filesystem labeled `BMGWTEST`
- a configfs USB gadget named `bmgw_spf71e`
- a read-only USB mass-storage LUN backed by the image

Status and teardown:

```bash
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh status
sudo ./rpi-setup/scripts/usb-otg-frame-test.sh teardown
```

## Boot Configuration

The Raspberry Pi Zero 2 W must expose a USB device controller. For this test,
`/boot/firmware/config.txt` needs the `dwc2` overlay under `[all]`:

```text
[all]
dtoverlay=dwc2,dr_mode=peripheral
```

If this line is placed under a model-specific section that does not match the
Zero 2 W, `/sys/class/udc` remains empty and the gadget cannot attach.

## Automation Follow-Up

The production image-export feature should build on this only after the frame
displays the baseline JPEG files. The next implementation design should decide:

- whether the exported drive stays read-only to the frame
- how `BMGateway` updates images without concurrent host/frame writes
- which generated views and filenames are stable
- whether updates require gadget detach, image rebuild, and reattach
- how the web UI exposes status and manual refresh controls

## Application Setting

`BMGateway` now includes a disabled-by-default `[usb_otg]` config section:

```toml
[usb_otg]
enabled = false
image_path = "/var/lib/bm-gateway/usb-otg/bmgateway-frame.img"
size_mb = 64
gadget_name = "bmgw_frame"
```

The Settings page exposes this as `USB OTG Image Export`. It checks whether
Linux currently exposes a USB gadget device controller under `/sys/class/udc`.
If the feature is enabled but no controller is detected, the page shows a red
warning explaining that the export cannot do anything until the Zero USB Plug
or OTG cable and `dwc2` peripheral mode are available.

The bootstrap installer installs `dosfstools` by default because FAT image
creation needs `mkfs.vfat`. Installers that do not need USB OTG support can
skip that package with:

```bash
./scripts/bootstrap-install.sh --skip-usb-otg-tools
```
