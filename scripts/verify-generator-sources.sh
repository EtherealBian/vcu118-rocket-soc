#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cy="$root/third_party/chipyard"; cd "$cy"
for d in generators/* fpga/fpga-shells sims/firesim tools/{rocket-dsp-utils,dsptools,cde,tapeout,firrtl2,fixedpoint}; do
  [[ -d $d ]] || continue
  record=$(git ls-tree HEAD -- "$d"); [[ $record == '160000 commit '* ]] || continue
  wanted=$(awk '{print $3}' <<< "$record"); actual=$(git -C "$d" rev-parse HEAD); [[ $wanted == "$actual" ]] || { echo "wrong submodule: $d $wanted != $actual" >&2; exit 1; }; printf '%s %s\n' "$actual" "$d"
done
for f in generators/vexiiriscv/VexiiRiscv/ext/SpinalHDL/build.sbt generators/rocket-chip/src/main/scala/rocket/RocketCore.scala sims/firesim/sim/midas/targetutils/src fpga/src/main/scala/vcu118/Configs.scala; do test -e "$f" || { echo "missing $f"; exit 1; }; done
echo 'GENERATOR_SOURCE_LOCK_PASS (top-level gitlinks for generator trees; skips non-hardware test dependencies)'
