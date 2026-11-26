#!/usr/bin/env bash
# Isolate the vendor IP only: the real board TL, converters, both async endpoints and five AXI channels are included.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; kit=$(realpath "${VCU_SIM_KIT:?}"); mkdir "${1:?fresh output dir}"; out=$(realpath "$1")
(cd "$kit" && sha256sum --status -c CANDIDATE.sha256)
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
obj=$(mktemp -d "${TMPDIR:-/tmp}/vcu118-mig-adapter.XXXXXXXX"); trap 'rm -rf -- "$obj"' EXIT
top=XilinxVCU118MIG
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module "$top" -DSYNTHESIS -Wno-fatal -F "$kit/sources.f" tests/mig_axi_model.sv "$root/tests/board_mig_adapter.cpp" -CFLAGS '-std=c++17 -O2' >"$out/verilate.log" 2>&1
make -C "$obj" -f V$top.mk -j2 PYTHON3=python3 CXX=g++ LINK=g++ AR=ar V$top >"$out/build.log" 2>&1
cp "$obj/V$top" "$out/sim"; cp "$obj/V${top}__verFiles.dat" "$out/verFiles.dat"; sha256sum "$kit/CANDIDATE.sha256" tests/board_mig_adapter.cpp tests/mig_axi_model.sv "$out/sim" >"$out/inputs.sha256"
"$out/sim" >"$out/result.txt"; cat "$out/result.txt"; grep -Fxq 'MIG_ADAPTER_MODEL_PASS cases=12 axi_channels=5' "$out/result.txt"
# Both faults preserve AXI addresses/lengths on the wire; a reference that used the slave's RAM would miss them.
for fault in alias strobe; do
 if "$out/sim" "+fault-$fault" >"$out/reject-$fault.txt" 2>&1; then echo "undetected fault-$fault" >&2; exit 1; fi
 grep -q '^AXI address/length/last/strobe/data mismatch, channel=4 address=' "$out/reject-$fault.txt"
done
echo 'MIG_ADAPTER_NEGATIVE_CONTROLS_PASS alias strobe'; touch "$out/test.ok"
