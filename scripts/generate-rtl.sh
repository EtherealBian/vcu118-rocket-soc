#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"
test "$(git -C "$cy" rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
test -f "$cy/generators/rocket-chip/src/main/scala/rocket/RocketCore.scala"; java -version; firtool --version; jq --version
[[ $(make -f /dev/null -p 2>/dev/null | grep -m1 "^\.FEATURES :=" || :) == *grouped-target* ]] || { echo "Need GNU Make with grouped targets (scripts/fetch-make.sh)"; exit 1; }
for t in objcopy objdump; do ln -sfn "$tools/bootlin/bin/riscv64-linux-$t" "$RISCV/bin/riscv64-unknown-elf-$t"; done
cat > "$RISCV/bin/riscv64-unknown-elf-gcc" <<EOF
#!/bin/sh
exec "$tools/bootlin/bin/riscv64-linux-gcc" -ffreestanding -fno-stack-protector -fno-pie -no-pie -Wl,--build-id=none "\$@"
EOF
chmod +x "$RISCV/bin/riscv64-unknown-elf-gcc"
make -B -C "$cy/fpga/src/main/resources/vcu118/sdboot" PBUS_CLK=100 bin
make -C "$cy/fpga" -f Makefile -f "$root/scripts/vcu-target.mk" SUB_PROJECT=vcu118 CONFIG=RocketVCU118Config vcu118-rtl-manifest
