#!/usr/bin/env bash
# Private functional simulator; generated HDL/objects must stay outside Git.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
mode=${1:?quad150 or perf175}; kit=$(realpath -m "${2:?fresh kit}"); obj=$(realpath -m "${3:?fresh Verilator directory}"); test ! -e "$kit" && test ! -e "$obj" || exit 2
case $mode in
 quad150) overlay=rtl/multicore/Quad150NineRocket.scala; harts=4; mhz=150;;
 perf175) overlay=rtl/perf/Perf175LargeBoom.scala; harts=1; mhz=175;;
 *) exit 2;;
esac
base=$(basename "$overlay" .scala); name=chipyard.fpga.vcu118.VCU118FPGATestHarness.${base}VCU118Config; gen=$cy/fpga/generated-src/$name
r=$(mktemp -d "$native/clock-link-rom.XXXXXXXX"); bash scripts/build-boot-gpt.sh "$r/boot" "$mode"
python3 scripts/check-board-dt.py "$gen/$name.dts" --rom "$r/boot/sdboot.elf" --harts "$harts" --mhz "$mhz"
if [[ $harts = 4 ]]; then python3 scripts/check-quad-tiles.py "$gen/gen-collateral" --nine
else python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 3 --rob-entries 96; fi
python3 scripts/seal-functional-model.py "$cy" "$gen" "$r/boot/sdboot.elf" "$kit" "$overlay"
VCU_SIM_KIT="$kit" VCU_SIM_OBJ="$obj" bash scripts/build-rtl-sim.sh
python3 scripts/check-model-kit.py "$obj" "$kit"
