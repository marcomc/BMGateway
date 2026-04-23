#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  usb-otg-frame-test.sh setup --source-dir <path> [options]
  usb-otg-frame-test.sh teardown [options]
  usb-otg-frame-test.sh status [options]

Options:
  --source-dir <path>       Directory containing test images for setup.
  --image-path <path>       FAT backing image path.
                            Default: /var/lib/bm-gateway/usb-otg/spf71e-test.img
  --size-mb <number>        Backing image size. Default: 64
  --gadget-name <name>      ConfigFS gadget name. Default: bmgw_spf71e
  --help                    Show this help text.
EOF
}

command_name="${1:-}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

source_dir=""
image_path="/var/lib/bm-gateway/usb-otg/spf71e-test.img"
size_mb="64"
gadget_name="bmgw_spf71e"
configfs_root="/sys/kernel/config/usb_gadget"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --source-dir)
      source_dir="${2:?missing value for --source-dir}"
      shift 2
      ;;
    --image-path)
      image_path="${2:?missing value for --image-path}"
      shift 2
      ;;
    --size-mb)
      size_mb="${2:?missing value for --size-mb}"
      shift 2
      ;;
    --gadget-name)
      gadget_name="${2:?missing value for --gadget-name}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    printf 'run as root\n' >&2
    exit 1
  fi
}

gadget_path() {
  printf '%s/%s\n' "${configfs_root}" "${gadget_name}"
}

first_udc() {
  local udc_path

  for udc_path in /sys/class/udc/*; do
    [[ -e "${udc_path}" ]] || return 0
    basename "${udc_path}"
    return 0
  done
}

ensure_usb_device_controller() {
  local udc

  modprobe libcomposite
  udc="$(first_udc)"
  if [[ -z "${udc}" ]]; then
    cat >&2 <<'EOF'
No USB device controller is available under /sys/class/udc.
On Raspberry Pi Zero/Zero 2 W, enable the dwc2 overlay and reboot:
  echo 'dtoverlay=dwc2' | sudo tee -a /boot/firmware/config.txt
EOF
    exit 1
  fi
}

detach_gadget() {
  local path
  path="$(gadget_path)"

  if [[ ! -d "${path}" ]]; then
    return
  fi

  if [[ -f "${path}/UDC" ]]; then
    printf '' >"${path}/UDC" || true
  fi

  find "${path}/configs" -mindepth 2 -maxdepth 2 -type l -exec rm -f {} + 2>/dev/null || true
  find "${path}/functions" -mindepth 1 -maxdepth 1 -type d -exec rmdir {} + 2>/dev/null || true
  find "${path}/configs" -mindepth 1 -depth -type d -exec rmdir {} + 2>/dev/null || true
  find "${path}/strings" -mindepth 1 -depth -type d -exec rmdir {} + 2>/dev/null || true
  rmdir "${path}" 2>/dev/null || true
}

unmount_image_mounts() {
  local mount_point
  local -a mount_points=()

  if ! command -v findmnt >/dev/null 2>&1; then
    return
  fi

  mapfile -t mount_points < <(findmnt -rn --source "${image_path}" -o TARGET 2>/dev/null || true)
  for mount_point in "${mount_points[@]}"; do
    umount "${mount_point}"
  done
}

populate_image() {
  local mount_dir

  if [[ -z "${source_dir}" ]]; then
    printf 'setup requires --source-dir\n' >&2
    exit 1
  fi
  if [[ ! -d "${source_dir}" ]]; then
    printf 'source directory not found: %s\n' "${source_dir}" >&2
    exit 1
  fi
  if ! find "${source_dir}" -maxdepth 1 -type f | grep -q .; then
    printf 'source directory has no files: %s\n' "${source_dir}" >&2
    exit 1
  fi

  command -v mkfs.vfat >/dev/null 2>&1 || {
    printf 'mkfs.vfat not found. Install dosfstools first.\n' >&2
    exit 1
  }

  unmount_image_mounts
  install -d -m 0755 "$(dirname "${image_path}")"
  truncate -s "${size_mb}M" "${image_path}"
  mkfs.vfat -F 32 -n BMGWTEST "${image_path}" >/dev/null

  mount_dir="$(mktemp -d)"
  trap 'umount "${mount_dir}" 2>/dev/null || true; rmdir "${mount_dir}" 2>/dev/null || true' RETURN
  mount -o loop,rw "${image_path}" "${mount_dir}"
  cp -R "${source_dir}/." "${mount_dir}/"
  sync
  umount "${mount_dir}"
  rmdir "${mount_dir}"
  trap - RETURN
}

setup_gadget() {
  local path udc
  path="$(gadget_path)"
  udc="$(first_udc)"

  detach_gadget
  mkdir -p "${path}"

  printf '0x1d6b\n' >"${path}/idVendor"
  printf '0x0104\n' >"${path}/idProduct"
  printf '0x0100\n' >"${path}/bcdDevice"
  printf '0x0200\n' >"${path}/bcdUSB"

  mkdir -p "${path}/strings/0x409"
  printf 'BMGWSPF71E001\n' >"${path}/strings/0x409/serialnumber"
  printf 'BMGateway\n' >"${path}/strings/0x409/manufacturer"
  printf 'BMGateway SPF-71E Photo Drive\n' >"${path}/strings/0x409/product"

  mkdir -p "${path}/configs/c.1/strings/0x409"
  printf 'Mass Storage\n' >"${path}/configs/c.1/strings/0x409/configuration"
  printf '120\n' >"${path}/configs/c.1/MaxPower"

  mkdir -p "${path}/functions/mass_storage.usb0"
  printf '1\n' >"${path}/functions/mass_storage.usb0/stall"
  printf '1\n' >"${path}/functions/mass_storage.usb0/lun.0/removable"
  printf '1\n' >"${path}/functions/mass_storage.usb0/lun.0/ro"
  printf '%s\n' "${image_path}" >"${path}/functions/mass_storage.usb0/lun.0/file"

  ln -s "${path}/functions/mass_storage.usb0" "${path}/configs/c.1/mass_storage.usb0"
  printf '%s\n' "${udc}" >"${path}/UDC"
}

show_status() {
  local path udc_available udc_value
  path="$(gadget_path)"
  udc_available="$(first_udc)"

  printf 'UDC available: %s\n' "${udc_available}"
  printf 'Image path: %s\n' "${image_path}"
  if [[ -f "${image_path}" ]]; then
    ls -lh "${image_path}"
  fi

  if [[ -d "${path}" ]]; then
    udc_value="$(cat "${path}/UDC" 2>/dev/null || true)"
    printf 'Gadget: %s\n' "${path}"
    printf 'Attached UDC: %s\n' "${udc_value:-detached}"
  else
    printf 'Gadget: not configured\n'
  fi
}

case "${command_name}" in
  setup)
    require_root
    ensure_usb_device_controller
    populate_image
    setup_gadget
    show_status
    ;;
  teardown)
    require_root
    detach_gadget
    show_status
    ;;
  status)
    show_status
    ;;
  --help | help | "")
    usage
    ;;
  *)
    printf 'Unknown command: %s\n' "${command_name}" >&2
    usage >&2
    exit 1
    ;;
esac
