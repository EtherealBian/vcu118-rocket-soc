#!/usr/bin/env bash
# No silicon, no JTAG, no physical DDR. Run the exact framed guest over the
# simulated UART and make sure two independent high-address mirroring faults fail.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh directory}; img=${2:?media fixture}; frame=${3:?UART frame}; obj=${VCU_SIM_OBJ:?model dir}; kit=${VCU_SIM_KIT:?unpacked kit}
test -s "$img"; test -s "$frame"; mkdir "$out"; out=$(realpath "$out"); python3 scripts/check-model-kit.py "$obj" "$kit"
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop; cp "$obj/VChipTop" "$out/sim"
sha256sum "$out/sim" "$img" "$frame" "$kit/CANDIDATE.sha256" >"$out/inputs.sha256"
for mode in uart5-address uart5-address-mirror29 uart5-address-mirror30; do
 "$out/sim" "$img" "$mode" 40000000 "$frame" >"$out/$mode.uart" 2>"$out/$mode.model"
 grep -F 'UART5_HANDOFF' "$out/$mode.uart"; grep -F "ROCKET_RTL_PASS mode=$mode " "$out/$mode.uart"
 if [[ $mode == uart5-address ]]; then grep -Fx 'ADDRESS_EXTERNAL_TL_CONFIRMED lines=256 dirty_puts=512 ordered_refills=512' "$out/$mode.model"; else grep -F 'VCU118_ADDR_FAIL data' "$out/$mode.uart"; fi
 echo "$mode completed" >"$out/$mode.ok"
done
printf 'ADDRESS_CHIPTOP_UART_AND_TWO_MIRROR_CONTROLS_PASS\n' | tee "$out/test.ok"
