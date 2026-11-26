#!/usr/bin/env bash
# Optional self-extracting image. Does not change ROM5, bitstream or the baseline firmware.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; raw=$(realpath "${1:?raw ROM5 payload}"); out=${2:?new output directory}; mkdir "$out"; out=$(realpath "$out")
cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-; src=$root/software/boot-pack
python3 scripts/pack-block.py "$raw" "$out" >"$out/block.json"
cd "$out"; cat > block.S <<'ASM'
.section .packed,"a",@progbits
.globl packed_start,packed_end
packed_start:
.incbin "block.lz4"
packed_end:
.section .note.GNU-stack,"",@progbits
ASM
"${cc}gcc" -Os -Wall -Wextra -Werror -nostdlib -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -static -no-pie -mcmodel=medany -mno-relax -msmall-data-limit=0 -mabi=lp64 -march=rv64imac_zicsr_zifencei -Wl,--build-id=none -I "$out" -T "$src/layout.ld" "$src/entry.S" "$src/boot.c" "$src/decode.c" block.S -o stage.elf
"${cc}objcopy" -O binary stage.elf stage.bin
"${cc}objdump" -d stage.elf >disasm.txt; "${cc}nm" -n stage.elf >symbols.txt
python3 - "$raw" <<'PY'
import hashlib,json,re,sys
from pathlib import Path as P
s=P('symbols.txt').read_text(); sy=lambda n:int(re.search(r'^([a-f0-9]+) \w '+n+r'$',s,re.M)[1],16)
b=P('stage.bin').read_bytes(); base=sy('_start'); block=P('block.lz4').read_bytes(); raw=P(sys.argv[1]).read_bytes()
assert base==0x84000000 and sy('__copy_end')==base+len(b) and 0<len(b)<=30<<20 and len(b)%8==0
assert b[sy('packed_start')-base:sy('packed_end')-base]==block
j=json.loads(P('block.json').read_text()); j.update(stage_sha256=hashlib.sha256(b).hexdigest(),stage_bytes=len(b),stage_copy_address=hex(base),output_address='0x80000000',stage_stack='0x87fff000',wire_bytes_saved=len(raw)-len(b))
P('stage.json').write_text(json.dumps(j,indent=2)+'\n');print(json.dumps(j,indent=2))
PY
python3 "$root/scripts/uart_frame.py" stage.bin stage.frame >frame.json
echo UART5_PACK1_BUILT_NOT_BOOT_EVIDENCE
