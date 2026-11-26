#!/usr/bin/env bash
# A separate Chipyard configuration. Refuse to overwrite a diverging local generator source.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
# Keep Bundle/BlackBox construction in the chipyard project, which inherits
# rocketLibDeps (including the full-Scala-version Chisel compiler plugin).
src=$root/rtl/accel/chipyard; dest=$cy/fpga/src/main/scala/vcu118/Dot4Rocket.scala
peripheral=$cy/generators/chipyard/src/main/scala/vcu118lab/Dot4Peripheral.scala
install_owned() {
 local in=$1 out=$2 previous=${3:-}
 if [[ -e $out ]]; then
  if cmp -s "$in" "$out"; then return; fi
  if [[ -z $previous || $(sha256sum "$out" | cut -d' ' -f1) != "$previous" ]]; then echo "refusing to replace diverged $out" >&2; return 1; fi
 fi
 mkdir -p "$(dirname "$out")"; cp "$in" "$out"
}
install_owned "$src/Dot4Peripheral.scala" "$peripheral"
install_owned "$src/Dot4Rocket.scala" "$dest" decd57f1851a9ebd6409fed0861668c5b0cdf39d8899fe05ef4ff357cc44ffa6
export VCU_DOT4_RTL=$root/rtl/accel/dot4_i8.sv; test -s "$VCU_DOT4_RTL"; test -s "$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.bin"; sha256sum "$src"/*.scala "$VCU_DOT4_RTL"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" SUB_PROJECT=vcu118 CONFIG=Dot4RocketVCU118Config GENERATOR_CLASSPATH="$cy/.classpath_cache/vcu118-dot4.jar" EXTRA_GENERATOR_REQS="$VCU_DOT4_RTL" vcu118-rtl-manifest
