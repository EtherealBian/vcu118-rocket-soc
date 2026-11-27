#!/usr/bin/env bash
# Sealed stock BOOM model only. No hardware, network, new Verilation or bitstream.
set -euo pipefail
cd "$(dirname "$0")/.."
kit=$(realpath "${1:?stock model kit}"); obj=$(realpath "${2:?stock model objects}"); out=${3:?fresh private output}
elf=$(realpath "${4:?strict release ELF}"); mkdir -m700 "$out"; out=$(realpath "$out"); tool=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
cc=$tool/bootlin-cpu-2025.08-1/bin/riscv64-linux-; inc=$tool/verilator/share/verilator/include
python3 scripts/check-model-kit.py "$obj" "$kit"
python3 - "$kit" "$obj" <<'PY'
from hashlib import sha256
from pathlib import Path
import json,sys,runpy
sys.path.insert(0,str(Path("scripts").resolve()))
k,o=map(Path,sys.argv[1:]); data=json.loads(Path('docs/perf-mega175-linux-entry.json').read_bytes()); p=data['models']['stock']
files={k/'CANDIDATE.sha256':p['CANDIDATE.sha256'],Path('tests/rocket_chiptop.cpp'):data['inputs']['rocket_chiptop.cpp'],
       o/'verilated.o':'2c3ba69e92629c65c1022ac91fc9065b6ba0c3dfacc78097a5620101cd687902',
       o/'verilated_threads.o':'a7f51711612d60da9b567a6d6bd6f167e42c26c620e38252683ec1c9a98fbeb7'}
for n in ['VChipTop__ALL.a','VChipTop___024root.h']:files[o/n]=p[n]
link=json.loads(Path("docs/perf-mega175-fixed-rom-link.json").read_bytes())
for n,h in link["inputs"].items():
    if n.startswith("chiptop_") and n.endswith(".hpp"): files[Path("tests")/n]=h
if runpy.run_path("scripts/review-clocked-rom-link.py")["verify_kit_clock"](k,175,1)!=link["rom_dtb_sha256"]:
    raise ValueError("model ROM mismatch")
for f,h in files.items():
    if sha256(f.read_bytes()).hexdigest()!=h:raise SystemExit('unexpected input: '+f.name)
PY
test "$("${cc}gcc" -dumpfullversion)" = 15.1.0
"${cc}gcc" -march=rv64imac_zicsr -mabi=lp64 -mno-relax -mcmodel=medany -fno-pie -no-pie -nostdlib -static \
  -Wl,--build-id=none,--no-relax -T software/bare/layout.ld tests/mega_timebase.S -o "$out/entry.elf"
"${cc}objcopy" -O binary "$out/entry.elf" "$out/entry.bin"; head -c8 "$out/entry.bin" >"$out/prefix"
python3 scripts/uart_frame.py "$out/prefix" "$out/prefix.frame"
"${CXX:-g++}" -std=c++17 -O2 -ffunction-sections -fdata-sections -Wl,--gc-sections -I"$obj" -I"$inc" -I"$inc/vltstd" \
  tests/mega_timebase.cpp "$obj/VChipTop__ALL.a" "$obj/verilated.o" "$obj/verilated_threads.o" -pthread -latomic -o "$out/model"
sha256sum "$kit/CANDIDATE.sha256" "$obj"/{VChipTop__ALL.a,VChipTop___024root.h,verilated.o,verilated_threads.o} "$out"/{entry.bin,prefix.frame,model} \
  scripts/{uart_frame.py,test-mega-timebase.sh,review-mega-timebase.py} tests/{rocket_chiptop.cpp,chiptop_*.hpp,mega_timebase.S,mega_timebase.cpp} software/bare/layout.ld >"$out/inputs.sha256"
nice -n 8 "$out/model" "$out/entry.bin" "$out/prefix.frame" "$out/rx.uart" | tee "$out/witness.txt"
sha256sum --quiet -c "$out/inputs.sha256"
python3 scripts/review-mega-timebase.py "$out" "$elf" >"$out/result.json"
