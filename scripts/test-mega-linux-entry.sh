#!/usr/bin/env bash
# Functional boot entry for the tested Linux firmware. Stops deliberately before
# userspace. No JTAG, hardware access, UART score, or physical timing assertion.
set -euo pipefail
cd "$(dirname "$0")/.."
role=${1:?stock or lvt}; kit=$(realpath "${2:?sealed model kit}"); obj=$(realpath "${3:?Verilator objects}"); pins=$(realpath "${4:?matching pin run}"); release=$(realpath "${5:?unpacked align Linux release}"); dir=${6:?fresh run directory}
case $role in stock|lvt);;*)exit 2;;esac
mkdir "$dir"; dir=$(realpath "$dir"); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools};inc="$tools/verilator/share/verilator/include"
python3 scripts/check-model-kit.py "$obj" "$kit"; (cd "$kit" && sha256sum --quiet -c CANDIDATE.sha256)
python3 - "$role" "$kit" "$obj" "$pins" "$release" "$dir" <<'PY'
import json,sys,runpy
from hashlib import sha256
from pathlib import Path
sys.path.insert(0,'scripts');from uart_frame import encode
role=sys.argv[1];k,o,p,r,d=map(Path,sys.argv[2:]);h=lambda v:sha256(v.read_bytes()).hexdigest();pinc=runpy.run_path('scripts/check-mega-regfile-chiptop.py')['model'](role,k,p)
if h(o/'VChipTop__ALL.a')!=pinc['inputs']['VChipTop__ALL.a']:raise ValueError('wrong archive')
boot=json.loads(Path('docs/linux-align-rocket-boot.json').read_bytes()); code=json.loads(Path('docs/linux-align-code.json').read_bytes()); profile,=[v for v in code['profiles'] if v['profile']=='g15-gc-lto-ooo-strict']; fw=(r/'fw_payload.bin').read_bytes();im=(r/'Image').read_bytes()
if (len(fw)!=boot['packed_stage']['raw_bytes'] or sha256(fw).hexdigest()!=boot['packed_stage']['raw_sha256'] or fw.count(im)!=1 or fw[0x200000:0x200000+len(im)]!=im or im[48:56]!=b'RISCV\0\0\0' or h(r/'coremark-g15-gc-lto-ooo-strict.elf')!=profile['elf_sha256']):raise ValueError('wrong firmware, kernel offset or companion ELF')
good=encode(fw[:8]);fault=bytearray(good);fault[12]^=1;(d/'prefix.frame').write_bytes(good);(d/'crc.frame').write_bytes(fault)
PY
cc=${CXX:-g++};"$cc" -std=c++17 -O2 -ffunction-sections -fdata-sections -Wl,--gc-sections -I"$obj" -I"$inc" -I"$inc/vltstd" tests/mega_linux_entry.cpp "$obj/VChipTop__ALL.a" "$obj/verilated.o" "$obj/verilated_threads.o" -pthread -latomic -o "$dir/model"
sha256sum "$dir"/{model,prefix.frame,crc.frame} "$kit"/CANDIDATE.sha256 "$obj"/{VChipTop__ALL.a,VChipTop___024root.h,verilated.o,verilated_threads.o} "$release"/{fw_payload.bin,Image,coremark-g15-gc-lto-ooo-strict.elf} "$pins/result.json" tests/{mega_linux_entry.cpp,rocket_chiptop.cpp,chiptop_*.hpp} >"$dir/inputs.sha256"
"$dir/model" crc "$release/fw_payload.bin" "$dir/crc.frame" >"$dir/crc.uart" 2>"$dir/crc.events"
"$dir/model" valid "$release/fw_payload.bin" "$dir/prefix.frame" >"$dir/boot.uart" 2>"$dir/boot.events"
sha256sum --quiet -c "$dir/inputs.sha256";echo MODELED_ENTRY_COMPLETE_NOT_A_LINUX_SCORE
