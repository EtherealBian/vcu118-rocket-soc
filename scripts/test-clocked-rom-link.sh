#!/usr/bin/env bash
# Exercise the linked ROM via pins only, without relinking/overwriting any existing simulator.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
kit=$(realpath "${1:?sealed kit}"); obj=$(realpath "${2:?matching Verilator model}"); mhz=${3:?peripheral MHz}; profile=${4:?single or quad}; out=${5:?fresh results directory}
case $mhz:$profile in 100:single|150:quad|175:single) ;; *) exit 2;; esac
mkdir "$out"; out=$(realpath "$out"); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; inc=$tools/verilator/share/verilator/include
python3 scripts/check-model-kit.py "$obj" "$kit"
(cd "$kit" && sha256sum --quiet -c CANDIDATE.sha256)
cc=$tools/bootlin/bin/riscv64-linux-
if [[ $profile = quad ]]; then bash scripts/build-quad-probe.sh "$out/probe"
else
 mkdir "$out/probe"
 "${cc}gcc" -nostdlib -static -no-pie -fno-pie -march=rv64imac_zicsr -mabi=lp64 -mno-relax -Wl,--build-id=none -T software/bare/layout.ld software/boot-uart/link-probe.S -o "$out/probe/probe.elf"
 "${cc}objcopy" -O binary "$out/probe/probe.elf" "$out/probe/probe.bin"
 python3 scripts/uart_frame.py "$out/probe/probe.bin" "$out/probe/probe.frame"
fi
# Same small CRC fault for either architecture, to avoid sending the entire quad fixture twice.
python3 - "$out" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0,'scripts');from uart_frame import encode
b=bytearray(encode(b'\x6f\x00\x00\x00')); b[12]^=1;(Path(sys.argv[1])/'crc.frame').write_bytes(b)
PY
trace_opts=(); trace_inputs=()
if [[ $profile = quad ]]; then
 lo=$(awk '$3=="quad_trace_begin" {print "0x"$1}' "$out/probe/symbols"); hi=$(awk '$3=="quad_trace_end" {print "0x"$1}' "$out/probe/symbols")
 [[ $lo =~ ^0x[0-9a-f]+$ && $hi =~ ^0x[0-9a-f]+$ ]] && ((hi-lo==32)) || exit 2
 trace_opts=(-DVCU_QUAD_OBSERVER "-DVCU_TRACE_LO=$lo" "-DVCU_TRACE_HI=$hi"); trace_inputs=(tests/quad_stage_observer.hpp)
fi
g++ "${trace_opts[@]}" -std=c++17 -O2 -ffunction-sections -fdata-sections -Wl,--gc-sections -I"$obj" -I"$inc" -I"$inc/vltstd" tests/rom_link.cpp "$obj/VChipTop__ALL.a" "$obj/verilated.o" "$obj/verilated_threads.o" -pthread -latomic -o "$out/model"
sha256sum "$out/model" "$kit/CANDIDATE.sha256" "$kit/rom/sdboot.bin" "$obj/VChipTop__ALL.a" "$out/probe/probe.elf" "$out/probe/probe.frame" "$out/crc.frame" tests/rom_link.cpp tests/rocket_chiptop.cpp tests/chiptop_*.hpp "${trace_inputs[@]}" >"$out/inputs.sha256"
wrong=100; [[ $mhz != 100 ]] || wrong=175
if "$out/model" "$wrong" "$out/probe/probe.frame" "$profile" >"$out/wrong.txt" 2>&1; then echo 'wrong clock accepted' >&2; exit 1; fi
grep -Fx "UART_EDGE_PERIOD_MISMATCH expected=$(((wrong*1000000+57600)/115200)) observed=$(((mhz*1000000+57600)/115200))" "$out/wrong.txt"
"$out/model" "$mhz" "$out/crc.frame" crc >"$out/crc.txt"
"$out/model" "$mhz" "$out/probe/probe.frame" "$profile" >"$out/pass.txt"
sha256sum --quiet -c "$out/inputs.sha256"
cat "$out/crc.txt"; tail -1 "$out/pass.txt"
python3 scripts/review-clocked-rom-link.py "$out" "$kit" "$mhz" "$profile" >"$out/result.partial"
mv "$out/result.partial" "$out/result.json"
