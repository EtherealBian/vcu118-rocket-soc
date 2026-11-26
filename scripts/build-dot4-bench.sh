#!/usr/bin/env bash
# Build opt-in scalar vs MMIO dot-product comparison and its exact UART frame.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out")
cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-
"${cc}gcc" -O2 -Wall -Wextra -Werror -ffreestanding -nostdlib -static -fno-pie -no-pie -fno-stack-protector -mcmodel=medany -march=rv64imac_zicsr -mabi=lp64 -Wl,--build-id=none -T software/bare/layout.ld software/bare/entry.S software/dot4/bench.c -o "$out/dotbench.elf"
"${cc}objcopy" -O binary "$out/dotbench.elf" "$out/dotbench.bin"
"${cc}readelf" -hW "$out/dotbench.elf" >"$out/header.txt"; grep -Eq 'Entry point address:[[:space:]]*0x80000000$' "$out/header.txt"
"${cc}nm" -n "$out/dotbench.elf" >"$out/symbols.txt"; "${cc}objdump" -d "$out/dotbench.elf" >"$out/disasm.txt"
python3 scripts/uart_frame.py "$out/dotbench.bin" "$out/dotbench.frame" >"$out/frame.json"
sha256sum "$out"/dotbench.{bin,elf,frame}; echo DOTBENCH_UART_PAYLOAD_BUILT
