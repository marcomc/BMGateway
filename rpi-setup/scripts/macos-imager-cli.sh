#!/bin/sh

set -eu

IMAGER_PATH="/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager"
IMAGE_URI=""
DESTINATION_DEVICE=""
FIRST_RUN_SCRIPT=""
CLOUDINIT_USERDATA=""
CLOUDINIT_NETWORKCONFIG=""
EXPECTED_SHA256=""
CUSTOM_CACHE_FILE=""
SECURE_BOOT_KEY=""
DEBUG=0
QUIET=0
DISABLE_VERIFY=0
DISABLE_EJECT=0
ENABLE_SYSTEM_DRIVES=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage:
  macos-imager-cli.sh --image <image-uri> --device <destination-device> [options]

Required:
  --image <image-uri>               Local file path or HTTPS URL for the OS image.
  --device <destination-device>     Target device, for example /dev/disk4.

Customisation options:
  --first-run-script <path>         Add a firstrun.sh payload to the image.
  --cloudinit-userdata <path>       Add a cloud-init user-data payload.
  --cloudinit-networkconfig <path>  Add a cloud-init network-config payload.

Validation and execution:
  --sha256 <hash>                   Expected SHA-256 for the image.
  --cache-file <path>               Custom cache file; requires --sha256.
  --secure-boot-key <path>          PEM private key for secure boot signing.
  --disable-verify                  Skip post-write verification.
  --disable-eject                   Do not eject the media after writing.
  --enable-writing-system-drives    Allow writing to system drives.
  --debug                           Enable Raspberry Pi Imager debug output.
  --quiet                           Suppress non-error console output.
  --dry-run                         Print the final command without executing it.
  --imager-path <path>              Override the bundled macOS app binary path.
  --help                            Show this help text.

Examples:
  macos-imager-cli.sh \
    --image ~/Downloads/raspios-lite.img.xz \
    --device /dev/disk4 \
    --first-run-script ./rpi-setup/examples/imager/bm-gateway-first-run.sh \
    --sha256 <expected-hash>

  macos-imager-cli.sh \
    --image https://example.invalid/raspios-lite.img.xz \
    --device /dev/disk4 \
    --cloudinit-userdata ./user-data.yaml \
    --cloudinit-networkconfig ./network-config.yaml
EOF
}

require_file() {
    if [ ! -f "$1" ]; then
        printf 'Required file not found: %s\n' "$1" >&2
        exit 2
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --image)
            IMAGE_URI="$2"
            shift 2
            ;;
        --device)
            DESTINATION_DEVICE="$2"
            shift 2
            ;;
        --first-run-script)
            FIRST_RUN_SCRIPT="$2"
            shift 2
            ;;
        --cloudinit-userdata)
            CLOUDINIT_USERDATA="$2"
            shift 2
            ;;
        --cloudinit-networkconfig)
            CLOUDINIT_NETWORKCONFIG="$2"
            shift 2
            ;;
        --sha256)
            EXPECTED_SHA256="$2"
            shift 2
            ;;
        --cache-file)
            CUSTOM_CACHE_FILE="$2"
            shift 2
            ;;
        --secure-boot-key)
            SECURE_BOOT_KEY="$2"
            shift 2
            ;;
        --disable-verify)
            DISABLE_VERIFY=1
            shift
            ;;
        --disable-eject)
            DISABLE_EJECT=1
            shift
            ;;
        --enable-writing-system-drives)
            ENABLE_SYSTEM_DRIVES=1
            shift
            ;;
        --debug)
            DEBUG=1
            shift
            ;;
        --quiet)
            QUIET=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --imager-path)
            IMAGER_PATH="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -z "${IMAGE_URI}" ] || [ -z "${DESTINATION_DEVICE}" ]; then
    printf 'Both --image and --device are required.\n' >&2
    usage >&2
    exit 2
fi

if [ -n "${CUSTOM_CACHE_FILE}" ] && [ -z "${EXPECTED_SHA256}" ]; then
    printf -- '--cache-file requires --sha256.\n' >&2
    exit 2
fi

if [ -n "${FIRST_RUN_SCRIPT}" ] && [ -n "${CLOUDINIT_USERDATA}" ]; then
    printf 'Choose either --first-run-script or --cloudinit-userdata, not both.\n' >&2
    exit 2
fi

if [ -n "${FIRST_RUN_SCRIPT}" ]; then
    require_file "${FIRST_RUN_SCRIPT}"
fi
if [ -n "${CLOUDINIT_USERDATA}" ]; then
    require_file "${CLOUDINIT_USERDATA}"
fi
if [ -n "${CLOUDINIT_NETWORKCONFIG}" ]; then
    require_file "${CLOUDINIT_NETWORKCONFIG}"
fi
if [ -n "${CUSTOM_CACHE_FILE}" ]; then
    require_file "${CUSTOM_CACHE_FILE}"
fi
if [ -n "${SECURE_BOOT_KEY}" ]; then
    require_file "${SECURE_BOOT_KEY}"
fi

if [ ! -x "${IMAGER_PATH}" ]; then
    printf 'Raspberry Pi Imager binary is not executable: %s\n' "${IMAGER_PATH}" >&2
    exit 2
fi

set -- "${IMAGER_PATH}" "--cli"

if [ "${DEBUG}" -eq 1 ]; then
    set -- "$@" "--debug"
fi
if [ "${QUIET}" -eq 1 ]; then
    set -- "$@" "--quiet"
fi
if [ "${DISABLE_VERIFY}" -eq 1 ]; then
    set -- "$@" "--disable-verify"
fi
if [ "${DISABLE_EJECT}" -eq 1 ]; then
    set -- "$@" "--disable-eject"
fi
if [ "${ENABLE_SYSTEM_DRIVES}" -eq 1 ]; then
    set -- "$@" "--enable-writing-system-drives"
fi
if [ -n "${EXPECTED_SHA256}" ]; then
    set -- "$@" "--sha256" "${EXPECTED_SHA256}"
fi
if [ -n "${CUSTOM_CACHE_FILE}" ]; then
    set -- "$@" "--cache-file" "${CUSTOM_CACHE_FILE}"
fi
if [ -n "${FIRST_RUN_SCRIPT}" ]; then
    set -- "$@" "--first-run-script" "${FIRST_RUN_SCRIPT}"
fi
if [ -n "${CLOUDINIT_USERDATA}" ]; then
    set -- "$@" "--cloudinit-userdata" "${CLOUDINIT_USERDATA}"
fi
if [ -n "${CLOUDINIT_NETWORKCONFIG}" ]; then
    set -- "$@" "--cloudinit-networkconfig" "${CLOUDINIT_NETWORKCONFIG}"
fi
if [ -n "${SECURE_BOOT_KEY}" ]; then
    set -- "$@" "--secure-boot-key" "${SECURE_BOOT_KEY}"
fi

set -- "$@" "${IMAGE_URI}" "${DESTINATION_DEVICE}"

if [ "${DRY_RUN}" -eq 1 ]; then
    printf 'Dry run command:\n'
    printf '  %s' "$1"
    shift
    for argument in "$@"; do
        printf ' %s' "${argument}"
    done
    printf '\n'
    exit 0
fi

exec "$@"
