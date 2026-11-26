#!/usr/bin/env bash
# Requires the generated clock-only candidate as the controlled comparator.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
[[ $(git -C "$cy" rev-parse HEAD) == 69eba860a352343e4ac6b6df0f3638a79a86ec78 ]]
base=chipyard.fpga.vcu118.VCU118FPGATestHarness; cfg=BufferedDebugRocketVCU118Config; gen=$cy/fpga/generated-src
cmp rtl/clocking/AlwaysClockedDebugRocket.scala "$cy/fpga/src/main/scala/vcu118/AlwaysClockedDebugRocket.scala"
test -s "$gen/$base.AlwaysClockedDebugRocketVCU118Config/gen-collateral/ChipTop.sv"
export VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/clocking/BufferedDebugRocket.scala VCU_BUFFER_MK=$root/scripts/vcu-buffered.mk
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-buffered-debug.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
s=$gen/$base.RocketVCU118Config; v=$gen/$base.$cfg; cmp "$s/$base.RocketVCU118Config.dts" "$v/$base.$cfg.dts"
python3 scripts/check-debug-clock.py "$s/gen-collateral/ChipTop.sv" "$v/gen-collateral/ChipTop.sv"
python3 scripts/check-debug-buffer.py "$gen/$base.AlwaysClockedDebugRocketVCU118Config/gen-collateral" "$v/gen-collateral"
echo BUFFERED_DEBUG_TOPOLOGY_GENERATED_NOT_TIMING_SIGNOFF
