#!/usr/bin/env bash
# First generate the separate Dot4 and buffered references. Never install this class in their source trees.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
[[ $(git -C "$cy" rev-parse HEAD) == 69eba860a352343e4ac6b6df0f3638a79a86ec78 ]]
base=chipyard.fpga.vcu118.VCU118FPGATestHarness; config=BufferedDot4RocketVCU118Config; gen=$cy/fpga/generated-src
src=$root/rtl/accel/chipyard
cmp "$src/Dot4Rocket.scala" "$cy/fpga/src/main/scala/vcu118/Dot4Rocket.scala"
cmp "$src/Dot4Peripheral.scala" "$cy/generators/chipyard/src/main/scala/vcu118lab/Dot4Peripheral.scala"
cmp rtl/clocking/AlwaysClockedDebugRocket.scala "$cy/fpga/src/main/scala/vcu118/AlwaysClockedDebugRocket.scala"
ref=$gen/$base.Dot4RocketVCU118Config; test -s "$ref/gen-collateral/ChipTop.sv"; test -s "$gen/$base.BufferedDebugRocketVCU118Config/gen-collateral/ChipTop.sv"
export VCU_DOT4_RTL=$root/rtl/accel/dot4_i8.sv VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/clocking/BufferedDebugRocket.scala
export VCU_COMBINED_CONFIG=$src/BufferedDot4Rocket.scala VCU_COMBINED_MK=$root/scripts/vcu-dot4-buffered.mk
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_COMBINED_MK" SUB_PROJECT=vcu118 CONFIG="$config" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-dot4-buffered.jar" EXTRA_GENERATOR_REQS="$VCU_DOT4_RTL $VCU_COMBINED_CONFIG" vcu118-rtl-manifest
v=$gen/$base.$config; cmp "$ref/$base.Dot4RocketVCU118Config.dts" "$v/$base.$config.dts"
python3 scripts/check-debug-clock.py "$ref/gen-collateral/ChipTop.sv" "$v/gen-collateral/ChipTop.sv"
python3 scripts/check-debug-buffer.py "$ref/gen-collateral" "$v/gen-collateral"
python3 scripts/check-board-dt.py "$v/$base.$config.dts" --rom "$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf"
echo COMBINED_DOT4_DEBUG_GENERATED_NOT_BOARD_VALIDATION
