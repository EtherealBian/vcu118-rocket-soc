#!/usr/bin/env bash
# Run against the actual candidate ChipTop; independent launcher, stable binary snapshot.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; obj=${VCU_SIM_OBJ:?select ROM4 simulation object directory}; kit=${VCU_SIM_KIT:?select matching ROM4 kit}; out=${1:?fresh result directory}; card=${2:?clean compact diagnostic image}; mkdir "$out"; out=$(realpath "$out"); [[ -s $kit/CANDIDATE.sha256 && -s $obj/VChipTop.mk ]]; python3 tests/make-rom4-faults.py "$card" "$out/cards"
export VERILATOR_ROOT=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator/share/verilator
flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop; cp "$obj/VChipTop" "$out/sim"; sha256sum "$out/sim" "$card" "$out"/cards/*.img
for mode in gpt-badheader gpt-badtable gpt-bounds; do
 "$out/sim" "$out/cards/$mode.img" "$mode" 18000000 > "$out/$mode.uart" 2> "$out/$mode.model"
 grep -F "ROCKET_RTL_PASS mode=$mode " "$out/$mode.uart"; grep -F FAULT_HALT_DPC "$out/$mode.model"; done
echo ROM4_GPT_NEGATIVE_MATRIX_PASS
