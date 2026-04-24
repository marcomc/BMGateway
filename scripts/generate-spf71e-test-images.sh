#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  generate-spf71e-test-images.sh [--output-dir <path>]

Generates a small Samsung SPF-71E compatibility test image set.
EOF
}

output_dir="output/spf71e-test-images"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --output-dir)
      output_dir="${2:?missing value for --output-dir}"
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

if command -v magick >/dev/null 2>&1; then
  magick_bin=(magick)
elif command -v convert >/dev/null 2>&1; then
  magick_bin=(convert)
else
  printf 'ImageMagick not found. Install magick or convert first.\n' >&2
  exit 1
fi

mkdir -p "${output_dir}"

make_image() {
  local filename="$1"
  local digit="$2"
  local background="$3"
  local accent="$4"
  local segment_draws="$5"
  local options=("${@:6}")

  "${magick_bin[@]}" \
    -size 480x234 \
    "gradient:${background}" \
    -colorspace sRGB \
    -fill '#101820' \
    -draw 'rectangle 0,0 479,233' \
    -fill "${background}" \
    -draw 'rectangle 6,6 473,227' \
    -fill "${accent}" \
    -draw 'rectangle 6,6 473,36' \
    -fill '#ffffff' \
    -draw "${segment_draws}" \
    -fill '#222222' \
    -draw 'rectangle 36,178 444,184 rectangle 36,196 444,202' \
    -fill "${accent}" \
    -draw 'rectangle 36,214 444,220' \
    "${options[@]}" \
    "${output_dir}/${filename}"

  printf '%s -> pattern %s\n' "${filename}" "${digit}"
}

make_image \
  "01_baseline_480x234_q92.jpg" \
  "01" \
  '#f8f8f0-#d8eee8' \
  '#0d6b57' \
  'rectangle 180,55 300,70 rectangle 180,70 195,115 rectangle 285,70 300,115 rectangle 180,115 300,130 rectangle 180,130 195,175 rectangle 285,130 300,175 rectangle 180,175 300,190' \
  -strip -interlace none -sampling-factor 4:2:0 -quality 92

make_image \
  "02_baseline_480x234_q75.jpg" \
  "02" \
  '#fff4d6-#e8eefc' \
  '#324fa8' \
  'rectangle 180,55 300,70 rectangle 285,70 300,115 rectangle 180,115 300,130 rectangle 180,130 195,175 rectangle 180,175 300,190' \
  -strip -interlace none -sampling-factor 4:2:0 -quality 75

make_image \
  "03_baseline_800x390_q85.jpg" \
  "03" \
  '#ececec-#d6e7ff' \
  '#7048a8' \
  'rectangle 180,55 300,70 rectangle 285,70 300,115 rectangle 180,115 300,130 rectangle 285,130 300,175 rectangle 180,175 300,190' \
  -strip -interlace none -resize 800x390! -sampling-factor 4:2:0 -quality 85

make_image \
  "04_progressive_480x234_q85.jpg" \
  "04" \
  '#ffe8e8-#f5f5f5' \
  '#a83a32' \
  'rectangle 180,70 195,115 rectangle 285,70 300,115 rectangle 180,115 300,130 rectangle 285,130 300,175' \
  -strip -interlace Plane -sampling-factor 4:2:0 -quality 85

"${magick_bin[@]}" \
  -size 480x234 xc:'#16202a' \
  -fill '#68d391' -draw 'rectangle 0,0 479,36' \
  -fill '#ffffff' \
  -draw 'rectangle 180,55 300,70 rectangle 180,70 195,115 rectangle 180,115 300,130 rectangle 285,130 300,175 rectangle 180,175 300,190' \
  -fill '#68d391' -draw 'rectangle 36,214 444,220' \
  "${output_dir}/05_png_control_480x234.png"

"${magick_bin[@]}" \
  -size 480x234 xc:'#202020' \
  -fill '#f6ad55' -draw 'rectangle 0,0 479,36' \
  -fill '#ffffff' \
  -draw 'rectangle 180,55 300,70 rectangle 180,70 195,115 rectangle 180,115 300,130 rectangle 180,130 195,175 rectangle 285,130 300,175 rectangle 180,175 300,190' \
  -fill '#f6ad55' -draw 'rectangle 36,214 444,220' \
  "${output_dir}/06_bmp_control_480x234.bmp"

cat >"${output_dir}/README.txt" <<'EOF'
BMGateway Samsung SPF-71E USB-OTG test image set

Expected best candidates:
- 01_baseline_480x234_q92.jpg
- 02_baseline_480x234_q75.jpg

The SPF-71E panel is 480x234 and the manual lists JPEG support.
Progressive and CMYK JPEG are documented as unsupported.
PNG and BMP are included only as controls.
EOF

printf 'Generated SPF-71E test images in %s\n' "${output_dir}"
