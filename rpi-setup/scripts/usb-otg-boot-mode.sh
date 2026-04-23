#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  usb-otg-boot-mode.sh prepare [--config-path <path>]
  usb-otg-boot-mode.sh restore [--config-path <path>]
  usb-otg-boot-mode.sh status [--config-path <path>]

Options:
  --config-path <path>       Raspberry Pi boot config path.
                             Default: /boot/firmware/config.txt
  --help                     Show this help text.
EOF
}

command_name="${1:-}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

config_path="/boot/firmware/config.txt"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --config-path)
      config_path="${2:?missing value for --config-path}"
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

python3 - "${command_name}" "${config_path}" <<'PY'
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

command = sys.argv[1]
path = Path(sys.argv[2])
begin = "# BMGateway USB OTG image export: begin"
end = "# BMGateway USB OTG image export: end"
managed_line = "dtoverlay=dwc2,dr_mode=peripheral"
previous_prefix = "# BMGateway previous: "


def backup() -> None:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bmgateway-usb-otg.{timestamp}.bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def strip_managed_block(lines: list[str]) -> list[str]:
    output: list[str] = []
    in_block = False
    for line in lines:
        if line == begin:
            in_block = True
            continue
        if in_block and line == end:
            in_block = False
            continue
        if in_block:
            if line.startswith(previous_prefix):
                output.append(line.removeprefix(previous_prefix))
            continue
        output.append(line)
    return output


def find_all_section(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == "[all]":
            return index
    return None


def next_section_index(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return index
    return len(lines)


def is_dwc2_line(line: str) -> bool:
    return line.strip().startswith("dtoverlay=dwc2")


def is_peripheral_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("dtoverlay=dwc2") and "dr_mode=peripheral" in stripped


def remove_all_section_peripheral_lines(lines: list[str]) -> list[str]:
    all_index = find_all_section(lines)
    if all_index is None:
        return lines
    section_end = next_section_index(lines, all_index)
    return [
        line
        for index, line in enumerate(lines)
        if not (all_index < index < section_end and is_peripheral_line(line))
    ]


def has_all_section_peripheral_line(lines: list[str]) -> bool:
    all_index = find_all_section(lines)
    if all_index is None:
        return False
    section_end = next_section_index(lines, all_index)
    return any(is_peripheral_line(line) for line in lines[all_index + 1 : section_end])


def prepare() -> None:
    if not path.exists():
        raise SystemExit(f"boot config not found: {path}")
    backup()
    lines = strip_managed_block(path.read_text(encoding="utf-8").splitlines())
    all_index = find_all_section(lines)
    if all_index is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(["[all]", begin, managed_line, end])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("prepared: added [all] USB OTG peripheral overlay")
        return

    section_end = next_section_index(lines, all_index)
    preserved: list[str] = []
    output: list[str] = []
    for index, line in enumerate(lines):
        if all_index < index < section_end and is_dwc2_line(line):
            if not is_peripheral_line(line):
                preserved.append(line)
            continue
        output.append(line)

    insert_at = all_index + 1
    block = [begin, *[f"{previous_prefix}{line}" for line in preserved], managed_line, end]
    output[insert_at:insert_at] = block
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print("prepared: USB OTG peripheral overlay will apply after reboot")


def restore() -> None:
    if not path.exists():
        raise SystemExit(f"boot config not found: {path}")
    backup()
    lines = strip_managed_block(path.read_text(encoding="utf-8").splitlines())
    lines = remove_all_section_peripheral_lines(lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("restored: BMGateway USB OTG boot overlay removed")


def status() -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    prepared = (begin in text and managed_line in text) or has_all_section_peripheral_line(lines)
    print("prepared" if prepared else "not prepared")


if command == "prepare":
    prepare()
elif command == "restore":
    restore()
elif command == "status":
    status()
elif command in {"--help", "help", ""}:
    raise SystemExit(0)
else:
    raise SystemExit(f"unknown command: {command}")
PY
