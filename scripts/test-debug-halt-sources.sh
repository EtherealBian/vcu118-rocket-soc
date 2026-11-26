#!/usr/bin/env bash
# Public DMI and hart-reset-status pins of the real debug module. No board I/O.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; kit=$(realpath "${VCU_SIM_KIT:?}"); mkdir "${1:?fresh output dir}"; out=$(realpath "$1")
(cd "$kit" && sha256sum --status -c CANDIDATE.sha256)
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator
export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
obj=$(mktemp -d "${TMPDIR:-/tmp}/vcu118-halt.XXXXXXXX"); trap 'rm -rf -- "$obj"' EXIT
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module TLDebugModule -DSYNTHESIS -Wno-fatal -F "$kit/sources.f" "$root/tests/debug_halt_sources.cpp" -CFLAGS '-std=c++17 -O2' >"$out/verilate.log" 2>&1
make -C "$obj" -f VTLDebugModule.mk -j"${JOBS:-2}" PYTHON3=python3 CXX=g++ LINK=g++ AR=ar VTLDebugModule >"$out/build.log" 2>&1
cp "$obj/VTLDebugModule" "$out/sim"; cp "$obj/VTLDebugModule__verFiles.dat" "$out/verFiles.dat"
sha256sum "$kit/CANDIDATE.sha256" tests/debug_halt_sources.cpp "$out/sim" >"$out/inputs.sha256"
"$out/sim" "$out/events.bin" >"$out/result.txt"; cat "$out/result.txt"; grep -qx 'GENERATED_DEBUG_HALT_SOURCES_PASS clock_cases=9' "$out/result.txt"; test "$(grep -c '^HALT_MERGE_CASE_PASS ' "$out/result.txt")" = 9; touch "$out/test.ok"
