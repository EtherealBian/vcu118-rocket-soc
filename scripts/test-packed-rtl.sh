#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd);cd "$root"
out=${1:?new results directory}; stage=${2:?packed 422-byte bare stage directory}; raw=${3:?original 422-byte diagnostic}; media=${4:?SD fixture (not accessed)}
: "${VCU_SIM_KIT:?unpacked UART5 kit}" "${VCU_SIM_OBJ:?matching ChipTop simulator}"
mkdir "$out"; python3 scripts/check-model-kit.py "$VCU_SIM_OBJ" "$VCU_SIM_KIT"; cp "$VCU_SIM_OBJ/VChipTop" "$out/sim"
python3 scripts/uart_frame.py "$stage/stage.bin" "$out/good.frame" >"$out/frame.json"; python3 scripts/make-pack-crc-control.py "$stage" "$raw" "$out/bad.frame"
for pair in uart5-pack-bare:good uart5-pack-badcrc:bad; do
 mode=${pair%:*}; fixture=${pair#*:}
 "$out/sim" "$media" "$mode" 40000000 "$out/$fixture.frame" >"$out/$fixture.uart" 2>"$out/$fixture.model"
 grep -F "ROCKET_RTL_PASS mode=$mode " "$out/$fixture.uart" |grep -F sectors_started=0
 printf '%s\n' "$mode" >"$out/$fixture.ok"
done
echo PACKED_DIAG_AND_INNER_CRC_REJECTION_PASS >"$out/test.ok"
