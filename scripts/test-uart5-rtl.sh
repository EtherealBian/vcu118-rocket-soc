#!/usr/bin/env bash
# Inputs are linked to a single ROM5 kit; copy the executable before any run.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
obj=${VCU_SIM_OBJ:?select matching ROM5 simulator}; kit=${VCU_SIM_KIT:?select ROM5 kit}
out=${1:?fresh output directory}; card=${2:?existing SD fixture, never accessed in ROM5}; bare=${3:?diagnostic binary}
test -s "$card"; test -s "$kit/CANDIDATE.sha256"; grep -aqF 'UART5_READY v1' "$kit/rom/sdboot.bin"; mkdir "$out"; out=$(realpath "$out")
python3 tests/make-uart5-faults.py "$bare" "$out/frames"
export VERILATOR_ROOT=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator/share/verilator
flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop
cp "$obj/VChipTop" "$out/sim"; sha256sum "$out/sim" "$kit/rtl/TLROM.sv" "$kit/rom/sdboot.bin" "$bare" "$out"/frames/* >"$out/inputs.sha256"
run(){
 local mode=$1 limit=$2
 "$out/sim" "$card" "$mode" "$limit" "$out/frames/$mode.frame" >"$out/$mode.uart" 2>"$out/$mode.model" || return 1
 grep -F "ROCKET_RTL_PASS mode=$mode " "$out/$mode.uart" || return 1
 if [[ $mode != uart5-bare ]]; then grep -F 'UART5_HALT_DPC=' "$out/$mode.model" || return 1; fi
 printf '%s\n' "$mode" >"$out/$mode.ok"
}
# The 2 s truncated-frame watchdog is 200 million real design cycles. Do not
# shorten the ROM timer for the test, or report it passed at simulation start.
run uart5-bare 22000000 & a=$!
run uart5-truncated 207000000 & b=$!
rc=0
for m in uart5-badmagic uart5-badlength uart5-badcrc; do run "$m" 2000000 || rc=1; done
wait "$a" || rc=1; wait "$b" || rc=1
if ((rc==0)); then echo UART5_SERIAL_ONLY_MATRIX_PASS; fi; exit "$rc"
