#!/usr/bin/env bash
# Build the standalone, sparse high-address diagnostic and its exact UART frame.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out")
cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-
"${cc}gcc" -Os -Wall -Wextra -Werror -ffreestanding -nostdlib -static -fno-pie -no-pie -fno-stack-protector -mcmodel=medany -march=rv64imac_zicsr -mabi=lp64 -Wl,--build-id=none -T software/bare/layout.ld software/bare/entry.S software/bare/address.c -o "$out/address.elf"
"${cc}objcopy" -O binary "$out/address.elf" "$out/address.bin"
"${cc}readelf" -hW "$out/address.elf" >"$out/header.txt"; grep -Eq 'Entry point address:[[:space:]]*0x80000000$' "$out/header.txt"
"${cc}nm" -n "$out/address.elf" >"$out/symbols.txt"; "${cc}objdump" -d "$out/address.elf" >"$out/disasm.txt"
python3 scripts/uart_frame.py "$out/address.bin" "$out/address.frame" >"$out/frame.json"
sha256sum "$out"/address.{bin,elf,frame}; echo ADDRESS_UART_PAYLOAD_BUILT
