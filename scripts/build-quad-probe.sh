#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh output directory}; mkdir "$out"; out=$(realpath "$out"); cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin/bin/riscv64-linux-
"${cc}gcc" -nostdlib -static -fno-pie -no-pie -march=rv64imac_zicsr -mabi=lp64 -mno-relax -Wl,--build-id=none -T software/bare/layout.ld software/smp/rom-probe.S -o "$out/probe.elf"
"${cc}objcopy" -O binary "$out/probe.elf" "$out/probe.bin"; "${cc}nm" -n "$out/probe.elf" > "$out/symbols"
python3 scripts/uart_frame.py "$out/probe.bin" "$out/probe.frame"
python3 - "$out" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);b=bytearray((p/'probe.frame').read_bytes());b[12]^=1;(p/'bad.frame').write_bytes(b)
PY
(cd "$out" && sha256sum probe.elf probe.bin probe.frame bad.frame symbols >inputs.sha256)
