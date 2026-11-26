#!/usr/bin/env bash
# Real generated wrangler, not the vendor MIG/PLL or a physical reset timing test.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; kit=$(realpath "${VCU_SIM_KIT:?}"); mkdir "${1:?fresh output dir}"; out=$(realpath "$1")
(cd "$kit" && sha256sum --status -c CANDIDATE.sha256)
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
obj=$(mktemp -d "${TMPDIR:-/tmp}/vcu118-wrangler.XXXXXXXX"); trap 'rm -rf -- "$obj"' EXIT
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module ResetWrangler -DSYNTHESIS -Wno-fatal -F "$kit/sources.f" "$root/tests/board_wrangler.cpp" -CFLAGS '-std=c++17 -O2' >"$out/verilate.log" 2>&1
make -C "$obj" -f VResetWrangler.mk -j2 PYTHON3=python3 CXX=g++ LINK=g++ AR=ar VResetWrangler >"$out/build.log" 2>&1
cp "$obj/VResetWrangler" "$out/sim"; cp "$obj/VResetWrangler__verFiles.dat" "$out/verFiles.dat"; sha256sum "$kit/CANDIDATE.sha256" tests/board_wrangler.cpp "$out/sim" >"$out/inputs.sha256"
"$out/sim" >"$out/result.txt"; cat "$out/result.txt"; grep -Fxq 'BOARD_WRANGLER_MODEL_PASS clock_cases=9 debounce_edges=10000 catch_edges=3' "$out/result.txt"; touch "$out/test.ok"
