#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cross=$tools/bootlin/bin/riscv64-linux-; out=${1:?provide fresh output directory}; mkdir "$out"; out=$(realpath "$out"); cd "$root/software/boot-gpt"
startup=entry.S; extra=()
case "${2:-gpt}" in
 gpt) source=boot.c; entry=load_gpt; tag=GPT;;
 uart5) source=../boot-uart/boot.c; entry=load_uart; tag=UART5;;
 perf175) source=../boot-uart/boot.c; entry=load_uart; tag=PERF_UART5; extra=(-DUART_PBUS_HZ=175000000u -DUART_TIMEBASE_HZ=175000u);;
 quad100|quad150) source=../boot-uart/boot.c; entry=load_uart; tag=QUAD_UART5; startup=../boot-uart/quad-entry.S; mhz=${2#quad}; extra=(-DUART_PBUS_HZ=${mhz}000000u -DUART_TIMEBASE_HZ=${mhz}000u);;
 *) echo 'boot mode must be gpt, uart5, perf175, quad100 or quad150'  >&2; exit 2;;
esac
"${cross}gcc" "${extra[@]}" -DBOOT_ROUTINE="$entry" -Os -ffreestanding -fno-builtin -ffunction-sections -fdata-sections -msmall-data-limit=0 -march=rv64imac_zicsr_zifencei -mabi=lp64 -mcmodel=medany -mno-relax -nostdlib -static -fno-pie -no-pie -fno-stack-protector -Wl,--gc-sections,--build-id=none -T layout.ld "$startup" "$source" -o "$out/sdboot.elf"
"${cross}objcopy" -O binary "$out/sdboot.elf" "$out/sdboot.bin"; "${cross}objdump" -d "$out/sdboot.elf" > "$out/boot.dis"; stat -c "${tag}_ROM_BYTES=%s" "$out/sdboot.bin"; sha256sum "$out"/sdboot.{elf,bin}
