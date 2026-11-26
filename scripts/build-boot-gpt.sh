#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cross=$tools/bootlin/bin/riscv64-linux-; out=${1:?provide fresh output directory}; mkdir "$out"; out=$(realpath "$out"); cd "$root/software/boot-gpt"
case "${2:-gpt}" in
 gpt) source=boot.c; entry=load_gpt; tag=GPT;;
 uart5) source=../boot-uart/boot.c; entry=load_uart; tag=UART5;;
 *) echo 'boot mode must be gpt or uart5' >&2; exit 2;;
esac
"${cross}gcc" -DBOOT_ROUTINE="$entry" -Os -ffreestanding -fno-builtin -ffunction-sections -fdata-sections -msmall-data-limit=0 -march=rv64imac_zicsr_zifencei -mabi=lp64 -mcmodel=medany -mno-relax -nostdlib -static -fno-pie -no-pie -fno-stack-protector -Wl,--gc-sections,--build-id=none -T layout.ld entry.S "$source" -o "$out/sdboot.elf"
"${cross}objcopy" -O binary "$out/sdboot.elf" "$out/sdboot.bin"; "${cross}objdump" -d "$out/sdboot.elf" > "$out/boot.dis"; stat -c "${tag}_ROM_BYTES=%s" "$out/sdboot.bin"; sha256sum "$out"/sdboot.{elf,bin}
