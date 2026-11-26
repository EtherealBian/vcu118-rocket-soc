#!/usr/bin/env bash
# Separate classpath/target; do not program hardware. Run after generator/ROM bootstrap.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
want=$(git -C "$cy" ls-tree HEAD generators/boom | awk '{print $3}'); test "$(git -C "$cy/generators/boom" rev-parse HEAD)" = "$want"
export VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/perf/PerfLargeBoom.scala VCU_BUFFER_MK=$root/scripts/vcu-buffered.mk
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
cfg=PerfLargeBoomVCU118Config; base=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-perf-large-boom.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
gen=$cy/fpga/generated-src/$base
python3 scripts/check-board-dt.py "$gen/$base.dts" --rom "$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf"
grep -Fqi 'boom' "$gen/$base.dts"; test -s "$gen/gen-collateral/BoomCore.sv"
echo PERF_LARGE_BOOM_RTL_AND_DT_ONLY
