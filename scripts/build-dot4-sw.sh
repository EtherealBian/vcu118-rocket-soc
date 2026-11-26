#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); t=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-; out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out"); cd "$root"
"${t}gcc" -Os -Wall -Wextra -Werror -ffreestanding -nostdlib -static -fno-pie -no-pie -fno-stack-protector -mcmodel=medany -march=rv64imac_zicsr -mabi=lp64 -Wl,--build-id=none -T software/bare/layout.ld software/bare/entry.S software/dot4/bare.c -o "$out/dot4.elf"
"${t}objcopy" -O binary "$out/dot4.elf" "$out/dot4.bin"; "${t}gcc" -Os -Wall -Wextra -Werror -static -s software/dot4/check.c -o "$out/dot4-check"; python3 scripts/make_sd.py --compact "$out/dot4.bin" "$out/dot4.img"; sha256sum "$out"/*
