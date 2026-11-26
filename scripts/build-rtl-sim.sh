#!/usr/bin/env bash
# Build functional ChipTop from the board's generated HDL, without substituting a different Rocket configuration.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; v=$tools/verilator; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; obj=${VCU_SIM_OBJ:-$native/verilated-stock}; mkdir -p "$obj"
export LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" VERILATOR_ROOT="$v/share/verilator"; "$v/bin/verilator_bin" --version
case ${VCU_SIM_CONFIG:-RocketVCU118Config} in RocketVCU118Config|Dot4RocketVCU118Config|AlwaysClockedDebugRocketVCU118Config|BufferedDebugRocketVCU118Config|BufferedDot4RocketVCU118Config) ;; *) echo 'unknown simulator configuration' >&2; exit 2;; esac
if [[ -n ${VCU_SIM_KIT:-} ]]; then manifest=$VCU_SIM_KIT/sources.f
else cfg=chipyard.fpga.vcu118.VCU118FPGATestHarness.${VCU_SIM_CONFIG:-RocketVCU118Config}; manifest=$root/third_party/chipyard/fpga/generated-src/$cfg/$cfg.vsrcs.f; fi
test -s "$manifest"
# Explicit top discards the separate vendor PLL + DDR shell; emulate only the external RAM and SD card.
"$v/bin/verilator_bin" --cc --exe --Mdir "$obj" --top-module ChipTop -DSYNTHESIS -Wno-fatal -F "$manifest" "$root/tests/rocket_chiptop.cpp" -CFLAGS '-O2 -std=c++17'
make -C "$obj" -f VChipTop.mk -j"${JOBS:-3}" CXX=g++ LINK=g++ AR=ar VChipTop
printf 'GENERATED_CHIPTOP_SIM_EXE=%s\n' "$obj/VChipTop"
