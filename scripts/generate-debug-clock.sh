#!/usr/bin/env bash
# Isolated timing experiment. No overwrite of stock/Dot4 configs or existing local edits.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
[[ $(git -C "$cy" rev-parse HEAD) == 69eba860a352343e4ac6b6df0f3638a79a86ec78 ]]
src=$root/rtl/clocking/AlwaysClockedDebugRocket.scala; dest=$cy/fpga/src/main/scala/vcu118/AlwaysClockedDebugRocket.scala
if [[ -e $dest ]]; then cmp "$src" "$dest"; else cp "$src" "$dest"; fi
cfg=AlwaysClockedDebugRocketVCU118Config; base=chipyard.fpga.vcu118.VCU118FPGATestHarness; gen=$cy/fpga/generated-src
rom=$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf; test -s "$rom"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-always-clocked-debug.jar" EXTRA_GENERATOR_REQS="$src" vcu118-rtl-manifest
stock=$gen/$base.RocketVCU118Config; variant=$gen/$base.$cfg
cmp "$stock/$base.RocketVCU118Config.dts" "$variant/$base.$cfg.dts"
python3 scripts/check-debug-clock.py "$stock/gen-collateral/ChipTop.sv" "$variant/gen-collateral/ChipTop.sv"
python3 scripts/check-board-dt.py "$variant/$base.$cfg.dts" --rom "$rom"
echo DEBUG_CLOCK_TOPOLOGY_CHECKED_NOT_TIMING_SIGNOFF
