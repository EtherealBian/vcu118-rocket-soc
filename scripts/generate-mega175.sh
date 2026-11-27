#!/usr/bin/env bash
# Generate the unretimed four-wide baseline at the desired board clock. This does not route or program a device.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
kit=$(realpath -m "${1:?fresh functional model kit}")
control=$(realpath "${2:?sealed 100 MHz four-wide model kit}")
test ! -e "$kit"; cmp "$control/config.scala" rtl/perf/PerfMegaBoom.scala
(cd "$control" && sha256sum --quiet -c CANDIDATE.sha256)
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
test "$(git -C "$cy/generators/boom" rev-parse HEAD)" = d2a64f7ca9fd914d9c686cb23edcd32d3465a02e
cfg=Perf175MegaBoomVCU118Config
base=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
gen="$cy/fpga/generated-src/$base"
romdir=$(mktemp -d "$native/mega175-rom.XXXXXXXX")
bash scripts/build-boot-gpt.sh "$romdir/uart" perf175
export VCU_PERF_ROM_BIN="$romdir/uart/sdboot.bin"
export VCU_BUFFER_ORIGINAL="$cy/generators/rocket-chip/src/main/scala/devices/debug/Periphery.scala"
export VCU_BUFFER_PATCHED="$native/vcu-buffered-src-v1/Periphery.scala"
export VCU_BUFFER_CONFIG="$root/rtl/perf/Perf175MegaBoom.scala" VCU_BUFFER_MK="$root/scripts/vcu-buffered.mk"
python3 scripts/prepare-debug-buffer.py "$VCU_BUFFER_ORIGINAL" "$VCU_BUFFER_PATCHED"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" -f "$VCU_BUFFER_MK" SUB_PROJECT=vcu118 CONFIG="$cfg" GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-perf175-mega-boom.jar" EXTRA_GENERATOR_REQS="$VCU_BUFFER_CONFIG" vcu118-rtl-manifest
python3 scripts/check-board-dt.py "$gen/$base.dts" --mhz 175 --harts 1 --rom "$romdir/uart/sdboot.elf"
python3 scripts/check-boom-shape.py "$gen/gen-collateral" --width 4 --rob-entries 128
python3 scripts/seal-functional-model.py "$cy" "$gen" "$romdir/uart/sdboot.elf" "$kit" "$VCU_BUFFER_CONFIG"
python3 scripts/check-wide-clock-delta.py "$control" "$kit" --family Mega
(cd "$kit" && sha256sum --quiet -c CANDIDATE.sha256)
echo MEGA175_MATCHED_HDL_AND_ROM_ONLY
