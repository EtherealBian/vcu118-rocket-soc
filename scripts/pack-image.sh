#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); d=$root/artifacts; t=$(mktemp -d "$d/.image.XXXXXX"); trap 'rmdir "$t" 2>/dev/null || :' EXIT
python3 "$root/scripts/make_sd.py" "$d/fw_payload.bin" "$t/vcu118-linux.img"
sgdisk -v "$t/vcu118-linux.img" | tee "$root/logs/linux-gpt.txt"; grep -q 'No problems found' "$root/logs/linux-gpt.txt"
mv -f "$t/vcu118-linux.img" "$d/vcu118-linux.img"
