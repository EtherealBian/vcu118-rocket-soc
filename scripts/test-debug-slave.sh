#!/usr/bin/env bash
# No physical board I/O. Commands execute on the halted hart in the generated model.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; obj=${VCU_SIM_OBJ:?}; kit=${VCU_SIM_KIT:?}; out=${1:?fresh output}; card=${2:?card fixture}
python3 scripts/check-model-kit.py "$obj" "$kit"; test -s "$card"; mkdir "$out"; out=$(realpath "$out")
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop
cp "$obj/VChipTop" "$out/sim"; sha256sum "$out/sim" "$kit/CANDIDATE.sha256" "$card" tests/chiptop_debug_slave.hpp >"$out/inputs.sha256"
"$out/sim" "$card" debug-slave-lanes 20000000 >"$out/test.uart" 2>"$out/test.model"
grep -Fx 'DEBUG_SLAVE_LANES_CHECKED stores=180 loads=180 bank_bytes=32 transfer_bytes=1,2,4,8 data_address=0x380' "$out/test.uart"
grep -E '^ROCKET_RTL_PASS mode=debug-slave-lanes cycles=[0-9]+ sectors_started=0 prehalt_tl_reads=1 posthalt_tl_reads=0 tl_external_writes=0$' "$out/test.uart"
echo GENERATED_DEBUG_SLAVE_LANES_CHECKED >"$out/test.ok"
