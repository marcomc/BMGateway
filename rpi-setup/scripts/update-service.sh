#!/usr/bin/env bash
set -euo pipefail

project_root="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"

exec sudo "${project_root}/rpi-setup/scripts/install-service.sh" "$@"
