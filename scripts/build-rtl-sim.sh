#!/usr/bin/env bash
# Build functional ChipTop from the board's generated HDL, without substituting a different Rocket configuration.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; v=$tools/verilator; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; obj=${VCU_SIM_OBJ:-$native/verilated-stock}; mkdir -p "$obj"
export LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" VERILATOR_ROOT="$v/share/verilator"; "$v/bin/verilator_bin" --version
board="$root/third_party/chipyard/fpga/generated-src/chipyard.fpga.vcu118.VCU118FPGATestHarness.RocketVCU118Config"; manifest=$(echo "$board"/*.vsrcs.f); test -s "$manifest"
if [[ -n ${VCU_SIM_KIT:-} ]]; then manifest=$VCU_SIM_KIT/sources.f; test -s "$manifest"; fi
# Explicit top discards the separate vendor PLL + DDR shell; emulate only the external RAM and SD card.
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module ChipTop -DSYNTHESIS -Wno-fatal -F "$manifest" "$root/tests/rocket_chiptop.cpp" -CFLAGS '-O2 -std=c++17'
make -C "$obj" -f VChipTop.mk -j"${JOBS:-3}" CXX=g++ LINK=g++ AR=ar VChipTop
printf 'GENERATED_CHIPTOP_SIM_EXE=%s\n' "$obj/VChipTop"
