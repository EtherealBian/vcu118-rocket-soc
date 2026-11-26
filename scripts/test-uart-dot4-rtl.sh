#!/usr/bin/env bash
# Exercise the real ROM receiver, with no debug preload and no SD commands.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
out=${1:?new output directory}; media=${2:?fixture image}; mode=${3:?uart5-dot4 or uart5-dotbench}; bin=${4:?raw payload}
case "$mode" in uart5-dot4|uart5-dotbench) ;; *) exit 2;; esac
: "${VCU_SIM_KIT:?unpacked candidate kit}" "${VCU_SIM_OBJ:?matching simulator object directory}"
mkdir "$out"
python3 scripts/check-model-kit.py "$VCU_SIM_OBJ" "$VCU_SIM_KIT"
python3 scripts/uart_frame.py "$bin" "$out/payload.frame" > "$out/frame.json"
cp "$VCU_SIM_OBJ/VChipTop" "$out/sim"
"$out/sim" "$media" "$mode" 40000000 "$out/payload.frame" >"$out/uart.txt" 2>"$out/model.txt"
python3 scripts/review-uart-dot4-rtl.py "$mode" "$out/uart.txt" > "$out/result.json"
printf '%s\n' "$mode" >"$out/test.ok"; cat "$out/result.json"
