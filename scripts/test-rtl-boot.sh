#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; obj=${VCU_SIM_OBJ:-$native/verilated-stock}; export LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" VERILATOR_ROOT="$v/share/verilator"
mode=${1:-sd-prefix}; file=${2:-$root/artifacts/vcu118-linux.img}; cycles=${3:-3000000}; test -s "$file"; test -s "$obj/VChipTop.mk"; flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j"${JOBS:-3}" CXX=g++ LINK=g++ AR=ar VChipTop >&2
args=(); if [[ $mode == debug-* ]]; then
 fw=${4:?debug preload required}; rom="$root/third_party/chipyard/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf"; if [[ -n ${VCU_SIM_KIT:-} ]]; then rom=$VCU_SIM_KIT/rom/sdboot.elf; fi; dtb=$(nm -n "$rom"|awk '$3=="dtb" {print "0x"$1}'); test -n "$dtb";sha256sum "$fw";args=("$fw" "$dtb"); fi
sha256sum "$file" "$obj/VChipTop"; "$obj/VChipTop" "$file" "$mode" "$cycles" "${args[@]}"
