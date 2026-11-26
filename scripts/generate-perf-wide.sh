#!/usr/bin/env bash
# Separate classpath/target; do not program hardware. Run after generator/ROM bootstrap.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
want=$(git -C "$cy" ls-tree HEAD generators/boom | awk '{print $3}'); test "$(git -C "$cy/generators/boom" rev-parse HEAD)" = "$want"
case ${1:-control} in
 mega) mhz=100; cfg=PerfMegaBoomVCU118Config; overlay=PerfMegaBoom; jar=vcu118-perf-mega-boom; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 control) mhz=100; cfg=PerfLargeBoomVCU118Config; overlay=PerfLargeBoom; jar=vcu118-perf-large-boom; rom="$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf";;
 perf175) mhz=175; cfg=Perf175LargeBoomVCU118Config; overlay=Perf175LargeBoom; jar=vcu118-perf175-large-boom
   romdir=$(mktemp -d "$native/perf175-rom.XXXXXXXX"); bash scripts/build-boot-gpt.sh "$romdir/uart" perf175
   rom=$romdir/uart/sdboot.elf; export VCU_PERF_ROM_BIN=$romdir/uart/sdboot.bin;;
 *) echo 'usage: generate-perf-wide.sh [control|perf175|mega]' >&2; exit 2;;
esac
export VCU_BUFFER_ORIGINAL=$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala
export VCU_BUFFER_PATCHED=$native/vcu-buffered-src-v1/Periphery.scala VCU_BUFFER_CONFIG=$root/rtl/perf/$overlay.scala VCU_BUFFER_MK=$root/scripts/vcu-buffered.mk
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
base=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/$jar.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
gen=$cy/fpga/generated-src/$base
python3 scripts/check-board-dt.py "$gen/$base.dts" --mhz "$mhz" --rom "$rom"
grep -Fqi 'boom' "$gen/$base.dts"; test -s "$gen/gen-collateral/BoomCore.sv"
if [[ $overlay == PerfMegaBoom ]]; then
 python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 4 --rob-entries 128
 echo PERF_MEGA_BOOM_RTL_AND_DT_ONLY; exit 0
fi
python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 3 --rob-entries 96
if [[ $mhz == 175 ]]; then echo PERF175_LARGE_BOOM_RTL_AND_DT_ONLY; else echo PERF_LARGE_BOOM_RTL_AND_DT_ONLY; fi
