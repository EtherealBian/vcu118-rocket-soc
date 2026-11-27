#!/usr/bin/env bash
# Model the same two fixture files used by the independent OOC implementation.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
d=$(realpath "${1:?fixture directory}")
o=${2:?fresh model directory}
mkdir "$o"; o=$(realpath "$o")
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator
export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
inputs=("$d/issue_ref.sv" "$d/issue_partial.sv" "$root/tests/issue_ready_miter.v" "$root/tests/issue_ready_slice.cpp")
sha256sum "${inputs[@]}" >"$o/inputs.sha256"
"$v/bin/verilator_bin" --cc --exe --top-module issue_ready_miter --Mdir "$o" "${inputs[2]}" "${inputs[0]}" "${inputs[1]}" "${inputs[3]}"
make -C "$o" -f Vissue_ready_miter.mk -j2 PYTHON3=python3 CXX=g++ LINK=g++ AR=ar Vissue_ready_miter
sha256sum --quiet -c "$o/inputs.sha256"
while read -r hash file; do printf 'ISSUE_SLICE_INPUT %s %s\n' "$hash" "${file##*/}"; done <"$o/inputs.sha256"
"$o/Vissue_ready_miter"
