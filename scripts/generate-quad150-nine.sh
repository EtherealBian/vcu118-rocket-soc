#!/usr/bin/env bash
# Separate classpath/target; do not program hardware. Run after generator/ROM bootstrap.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
want=$(git -C "$cy" ls-tree HEAD generators/boom | awk '{print $3}'); test "$(git -C "$cy/generators/boom" rev-parse HEAD)" = "$want"
export VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/multicore/Quad150NineRocket.scala VCU_BUFFER_MK=$root/scripts/vcu-quad-nine.mk
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
export VCU_DEEP_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/rocket/RocketCore.scala VCU_DEEP_PATCHED=$native/vcu-quad-nine-v2/RocketCore.scala
python3 scripts/prepare-nine-rocket.py "$VCU_DEEP_ORIGINAL" "$VCU_DEEP_PATCHED"
export VCU_FE_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/rocket/Frontend.scala VCU_FE_PATCHED=$native/vcu-quad-nine-v2/Frontend.scala
python3 scripts/prepare-nine-rocket.py --frontend "$VCU_FE_ORIGINAL" "$VCU_FE_PATCHED"
romdir=$(mktemp -d "$native/quad-nine-rom.XXXXXXXX"); bash scripts/build-boot-gpt.sh "$romdir/uart" quad150
export VCU_QUAD_ROM_BIN=$romdir/uart/sdboot.bin
cfg=Quad150NineRocketVCU118Config; base=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-quad150-nine.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
gen=$cy/fpga/generated-src/$base
python3 scripts/check-board-dt.py "$gen/$base.dts" --rom "$romdir/uart/sdboot.elf" --harts 4 --mhz 150
python3 scripts/check-quad-tiles.py "$gen/gen-collateral" --nine
echo QUAD_NINE_GENERATED_ONLY_NO_TRACE_OR_TIMING
