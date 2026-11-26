#!/usr/bin/env bash
# Debug-preloaded functional RTL; not a serial boot, Linux run or physical score.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
kit=$(realpath "${1:?generated kit}"); obj=$(realpath "${2:?Verilated object directory}"); diag=$(realpath "${3:?diagnostic build}"); rom=$(realpath "${4:?matching sdboot.elf}"); out=${5:?fresh results directory}; mkdir "$out"; out=$(realpath "$out")
opts=()
case ${6:-} in
 '') ;;
 --boom-events) cmp "$kit/config.scala" rtl/perf/PerfMediumBoom.scala; grep -Fxq -- '-DVCU_BOOM_EVENTS=1' "$diag/build-flags.txt"; opts+=(--boom-events);;
 *) echo 'unknown review mode' >&2; exit 2;;
esac
export VERILATOR_ROOT=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator/share/verilator
# A single lock covers identity check, harness relink and pinning the executable.
(
 flock -x 9
 python3 scripts/check-model-kit.py "$obj" "$kit"
 make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop
 cp "$obj/VChipTop" "$out/sim"
) 9>"$obj/.build-lock"
cmp "$rom" "$kit/rom/sdboot.elf"
(cd "$diag" && sha256sum -c inputs.sha256)
dtb=$(nm -n "$rom" | awk '$3=="dtb" {print "0x"$1}'); test -n "$dtb"
sha256sum "$out/sim" "$kit/CANDIDATE.sha256" "$diag/window.bin" "$diag/window.elf" "$rom" "$root/tests/rocket_chiptop.cpp" >"$out/inputs.sha256"
"$out/sim" artifacts/bare-compact.img debug-cpu-window 40000000 "$diag/window.bin" "$dtb" >"$out/console.txt" 2>"$out/simulator.txt"
python3 scripts/review-cpu-window.py "$out" "$kit" "$diag" "${opts[@]}" >"$out/result.partial"
mv "$out/result.partial" "$out/result.json"
