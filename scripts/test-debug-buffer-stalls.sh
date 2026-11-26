#!/usr/bin/env bash
# WSL, pinned Verilator 5.022. Exercise both channels at once in generated SV.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
kit=$(realpath "${VCU_SIM_KIT:?select buffered kit}"); out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out")
# Check the full kit content before selecting the queue hierarchy.
(cd "$kit" && sha256sum --status -c CANDIDATE.sha256)
name=TLBuffer_a12d64s8k1z2u; v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator
export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
obj=$(mktemp -d "${TMPDIR:-/tmp}/vcu118-stalls.XXXXXXXX"); trap 'rm -rf -- "$obj"' EXIT
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module "$name" -DSYNTHESIS -Wno-fatal -y "$kit/rtl" "$kit/rtl/$name.sv" "$root/tests/debug_buffer_stalls.cpp" -CFLAGS '-std=c++17 -O2' >"$out/verilate.log" 2>&1
make -C "$obj" -f "V$name.mk" -j2 PYTHON3=python3 CXX=g++ LINK=g++ AR=ar "V$name" >"$out/build.log" 2>&1
cp "$obj/V$name" "$out/sim"; cp "$obj/V${name}__verFiles.dat" "$out/verFiles.dat"
sha256sum "$kit/CANDIDATE.sha256" tests/debug_buffer_stalls.cpp "$out/sim" >"$out/inputs.sha256"
"$out/sim" >"$out/result.txt"; cat "$out/result.txt"; grep -qx 'GENERATED_AD_BUFFER_STALL_RESET_PASS cycles=4112' "$out/result.txt"
touch "$out/test.ok"
