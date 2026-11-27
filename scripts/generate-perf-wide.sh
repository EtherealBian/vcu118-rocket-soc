#!/usr/bin/env bash
# Separate classpath/target; do not program hardware. Run after generator/ROM bootstrap.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
want=$(git -C "$cy" ls-tree HEAD generators/boom | awk '{print $3}'); test "$(git -C "$cy/generators/boom" rev-parse HEAD)" = "$want"
case ${1:-control} in
 early-way) mhz=100; cfg=PerfEarlyWayBoomVCU118Config; overlay=PerfEarlyWayBoom; jar=vcu118-perf-early-way; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 no-fast-load) mhz=100; cfg=PerfNoFastLoadBoomVCU118Config; overlay=PerfNoFastLoadBoom; jar=vcu118-perf-no-fast-load; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 partial-mega) mhz=100; cfg=PerfPartialMegaBoomVCU118Config; overlay=PerfPartialMegaBoom; jar=vcu118-perf-partial-mega; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 mega) mhz=100; cfg=PerfMegaBoomVCU118Config; overlay=PerfMegaBoom; jar=vcu118-perf-mega-boom; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 control) mhz=100; cfg=PerfLargeBoomVCU118Config; overlay=PerfLargeBoom; jar=vcu118-perf-large-boom; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 perf175) mhz=175; cfg=Perf175LargeBoomVCU118Config; overlay=Perf175LargeBoom; jar=vcu118-perf175-large-boom
   romdir=$(mktemp -d "$native/perf175-rom.XXXXXXXX"); bash scripts/build-boot-gpt.sh "$romdir/uart" perf175
   rom=$romdir/uart/sdboot.elf; export VCU_PERF_ROM_BIN=$romdir/uart/sdboot.bin;;
 *) echo 'usage: generate-perf-wide.sh [control|perf175|mega|no-fast-load|partial-mega|early-way]' >&2; exit 2;;
esac
export VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/perf/$overlay.scala VCU_BUFFER_MK=$root/scripts/vcu-buffered.mk
if [[ $overlay == PerfEarlyWayBoom ]]; then
 # Same one-source SBT substitution recipe as the issue experiment; paths name the D-cache instead.
 export VCU_ISSUE_ORIGINAL=$cy/generators/boom/src/main/scala/v3/lsu/dcache.scala
 export VCU_ISSUE_PATCHED=$native/vcu-early-mshr-way-v1/dcache.scala VCU_BUFFER_MK=$root/scripts/vcu-issue-partials.mk
 python3 scripts/prepare-mshr-way.py "$VCU_ISSUE_ORIGINAL" "$VCU_ISSUE_PATCHED"
fi
if [[ $overlay == PerfPartialMegaBoom ]]; then
 export VCU_ISSUE_ORIGINAL=$cy/generators/boom/src/main/scala/v3/exu/issue-units/issue-unit-age-ordered.scala
 export VCU_ISSUE_PATCHED=$native/vcu-issue-partials-v1/issue-unit-age-ordered.scala VCU_BUFFER_MK=$root/scripts/vcu-issue-partials.mk
 python3 scripts/prepare-issue-partials.py "$VCU_ISSUE_ORIGINAL" "$VCU_ISSUE_PATCHED"
fi
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
base=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/$jar.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
gen=$cy/fpga/generated-src/$base
python3 scripts/check-board-dt.py "$gen/$base.dts" --mhz "$mhz" --rom "$rom"
grep -Fqi 'boom' "$gen/$base.dts"; test -s "$gen/gen-collateral/BoomCore.sv"
if [[ $overlay == PerfMegaBoom || $overlay == PerfPartialMegaBoom ]]; then
 python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 4 --rob-entries 128
 if [[ $overlay == PerfPartialMegaBoom ]]; then
  python3 scripts/check-issue-partials.py "$gen/gen-collateral"
  echo PERF_PARTIAL_MEGA_RTL_AND_DT_ONLY
 else echo PERF_MEGA_BOOM_RTL_AND_DT_ONLY; fi; exit 0
fi
python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 3 --rob-entries 96
if [[ $overlay == PerfEarlyWayBoom ]]; then echo PERF_EARLY_WAY_RTL_AND_DT_ONLY; exit 0; fi
if [[ $overlay == PerfNoFastLoadBoom ]]; then echo PERF_NO_FAST_LOAD_BOOM_RTL_AND_DT_ONLY; exit 0; fi
if [[ $mhz == 175 ]]; then echo PERF175_LARGE_BOOM_RTL_AND_DT_ONLY; else echo PERF_LARGE_BOOM_RTL_AND_DT_ONLY; fi
