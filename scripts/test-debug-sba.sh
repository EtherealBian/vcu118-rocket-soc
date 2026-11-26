#!/usr/bin/env bash
# Build the independent mailbox guest and test DMI system-bus access through the real Rocket RTL.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh output directory}; img=${2:?test disk fixture}; obj=${VCU_SIM_OBJ:?matching prebuilt RTL model object directory}; kit=${VCU_SIM_KIT:?matching unpacked RTL kit}; test -s "$obj/VChipTop.mk"; test -s "$kit/sources.f"; test -s "$img"; mkdir "$out"; out=$(realpath "$out")
# Refuse a mismatched object directory: checking a different kit's SHA says
# nothing about which generated RTL was in the tested executable.
python3 - "$obj/VChipTop__verFiles.dat" "$kit/sources.f" <<'PY'
from pathlib import Path
import shlex,sys
records=Path(sys.argv[1]).read_text().splitlines()
commands=[s[3:-1] for s in records if s.startswith('C "') and s.endswith('"')]
assert len(commands)==1
args=shlex.split(commands[0]); assert args.count('-F')==1
assert Path(args[args.index('-F')+1]).resolve()==Path(sys.argv[2]).resolve(), 'simulator was elaborated from another kit'
PY
tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cc=$tools/bootlin/bin/riscv64-linux-; v=$tools/verilator; export VERILATOR_ROOT=$v/share/verilator LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"${cc}gcc" -Os -Wall -Wextra -Werror -ffreestanding -nostdlib -static -fno-pie -no-pie -fno-stack-protector -mcmodel=medany -march=rv64imac_zicsr -mabi=lp64 -Wl,--build-id=none -T software/bare/layout.ld software/bare/entry.S software/bare/sba-mailbox.c -o "$out/mailbox.elf"
"${cc}objcopy" -O binary "$out/mailbox.elf" "$out/mailbox.bin"; flock "$obj/.build-lock" make -C "$obj" -f VChipTop.mk -j2 CXX=g++ LINK=g++ AR=ar VChipTop; cp "$obj/VChipTop" "$out/sim"
sha256sum "$out/sim" "$out/mailbox.bin" "$out/mailbox.elf" "$img" "$kit/rtl/ChipTop.sv" "$kit/rtl/TLROM.sv" >"$out/inputs.sha256"
"$out/sim" "$img" sba-mailbox 5000000 "$out/mailbox.bin" >"$out/test.uart" 2>"$out/test.model"
grep -F 'SBA_GUEST_READBACK expected=' "$out/test.model"; grep -F 'ROCKET_RTL_PASS mode=sba-mailbox ' "$out/test.uart"; echo SBA_MAILBOX_CHIPTOP_PASS >"$out/test.ok"
