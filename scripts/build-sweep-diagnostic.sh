#!/usr/bin/env bash
# Build the standalone 2032 MiB coverage diagnostic and its exact UART frame.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out")
cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-
"${cc}gcc" -Os -Wall -Wextra -Werror -ffreestanding -nostdlib -static -fno-pie -no-pie -fno-stack-protector -mcmodel=medany -march=rv64imac_zicsr -mabi=lp64 -Wl,--build-id=none -T software/bare/layout.ld software/bare/entry.S software/bare/sweep.c -o "$out/sweep.elf"
"${cc}objcopy" -O binary "$out/sweep.elf" "$out/sweep.bin"
"${cc}readelf" -hW "$out/sweep.elf" >"$out/header.txt"; grep -Eq 'Entry point address:[[:space:]]*0x80000000$' "$out/header.txt"
"${cc}nm" -n "$out/sweep.elf" >"$out/symbols.txt"; "${cc}objdump" -d "$out/sweep.elf" >"$out/disasm.txt"
python3 - "$out/symbols.txt" <<'BOUNDS'
import re,sys
symbols=open(sys.argv[1]).read(); stack=int(re.search(r'^([0-9a-f]+) [A-Za-z] __stack_top$',symbols,re.M)[1],16)
assert 0x80000000 < stack < 0x80800000 and 0x8ffff000//0x800000 == 0x80000000//0x800000+31
assert 254*8*1024*1024==2130706432
BOUNDS
python3 scripts/uart_frame.py "$out/sweep.bin" "$out/sweep.frame" >"$out/frame.json"
sha256sum "$out"/sweep.{bin,elf,frame}; echo SWEEP_UART_PAYLOAD_BUILT
