#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cross=$tools/bootlin/bin/riscv64-linux-; out=${1:?provide fresh output directory}; mkdir "$out"; out=$(realpath "$out"); cd "$root/software/boot-gpt"
"${cross}gcc" -Os -ffreestanding -fno-builtin -ffunction-sections -fdata-sections -msmall-data-limit=0 -march=rv64imac_zicsr_zifencei -mabi=lp64 -mcmodel=medany -mno-relax -nostdlib -static -fno-pie -no-pie -fno-stack-protector -Wl,--gc-sections,--build-id=none -T layout.ld entry.S boot.c -o "$out/sdboot.elf"
"${cross}objcopy" -O binary "$out/sdboot.elf" "$out/sdboot.bin"; "${cross}objdump" -d "$out/sdboot.elf" > "$out/boot.dis"; stat -c 'GPT_ROM_BYTES=%s' "$out/sdboot.bin"; sha256sum "$out"/sdboot.{elf,bin}
