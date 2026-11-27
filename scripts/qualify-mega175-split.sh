#!/usr/bin/env bash
# Qualify only the single-hart, four-wide 175 MHz target. NO board access or Vivado here.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
control=$(realpath "${1:?100 MHz stock Mega kit}"); stock=$(realpath "${2:?175 MHz stock Mega kit}"); sobj=$(realpath "${3:?stock ChipTop object directory}"); pins=$(realpath "${4:?stock pin capture}")
fixed=$(realpath -m "${5:?new native fixed kit}"); fobj=$(realpath -m "${6:?new native fixed ChipTop object directory}"); out=$(realpath -m "${7:?new evidence directory}"); board=$(realpath -m "${8:?new private implementation kit on a Windows-accessible drive}")
for f in "$fixed" "$fobj" "$out" "$board"; do test ! -e "$f"; done
mkdir "$out"
python3 scripts/review-clocked-rom-link.py "$pins" "$stock" 175 single >"$out/stock-pin.json"
cmp "$out/stock-pin.json" "$pins/result.json"
python3 scripts/derive-mega-halt-model.py "$stock" "$fixed" --control100 "$control"
VCU_SIM_KIT="$stock" bash scripts/test-debug-halt-sources.sh "$out/orig-debug" >"$out/orig-debug.txt" 2>&1
VCU_SIM_KIT="$fixed" bash scripts/test-debug-halt-sources.sh "$out/fix-debug" >"$out/fix-debug.txt" 2>&1
python3 scripts/review-mega-halt.py "$stock" "$fixed" "$out/orig-debug" "$out/fix-debug" --control100 "$control" >"$out/halt.json"
VCU_SIM_KIT="$fixed" VCU_SIM_OBJ="$fobj" bash scripts/build-rtl-sim.sh >"$out/build.txt" 2>&1
bash scripts/test-clocked-rom-link.sh "$fixed" "$fobj" 175 single "$out/fix-pin" >"$out/fix-pin.txt" 2>&1
python3 scripts/review-clocked-rom-link.py "$out/fix-pin" "$fixed" 175 single >"$out/fix-pin.json"
cmp "$out/fix-pin.json" "$out/fix-pin/result.json"
python3 scripts/promote-wide-model.py "$stock" "$sobj" 175 "$board" --family Mega --fixed "$fixed" --fixed-obj "$fobj" --control100 "$control" >"$out/promote.txt"
python3 scripts/verify-mega-impl-inputs.py "$board" "$out" >"$out/implementation-inputs.partial"
mv "$out/implementation-inputs.partial" "$out/implementation-inputs.json"
echo FOUR_WIDE_175_BUILD_INPUTS_ONLY_NO_DEVICE_ACCESS
