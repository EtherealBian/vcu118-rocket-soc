#!/usr/bin/env bash
# A separate Chipyard configuration. Refuse to overwrite a diverging local generator source.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
src=$root/rtl/accel/chipyard/Dot4Rocket.scala; dest=$cy/fpga/src/main/scala/vcu118/Dot4Rocket.scala
if [[ -e $dest ]]; then cmp "$src" "$dest"; else cp "$src" "$dest"; fi
export VCU_DOT4_RTL=$root/rtl/accel/dot4_i8.sv; test -s "$VCU_DOT4_RTL"; test -s "$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.bin"; sha256sum "$src" "$VCU_DOT4_RTL"
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" SUB_PROJECT=vcu118 CONFIG=Dot4RocketVCU118Config vcu118-rtl-manifest
