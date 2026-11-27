#!/usr/bin/env bash
# Replay actual guest snapshots in the sealed stock four-wide model, no board access.
set -euo pipefail
cd "$(dirname "$0")/.."
kit=$(realpath "${1:?sealed kit}"); obj=$(realpath "${2:?Verilator objects}")
guest=$(realpath "${3:?captured guest with replay memories}"); out=${4:?fresh private output directory}
mkdir -m700 "$out"; out=$(realpath "$out"); tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
inc="$tools/verilator/share/verilator/include"
python3 scripts/check-model-kit.py "$obj" "$kit"
python3 - "$kit" "$obj" <<'PY'
import hashlib,json,sys
from pathlib import Path
k,o=map(Path,sys.argv[1:]); pin=json.loads(Path('docs/perf-mega175-linux-entry.json').read_bytes())
keys={k/'CANDIDATE.sha256':pin['models']['stock']['CANDIDATE.sha256'],
      o/'verilated.o':'2c3ba69e92629c65c1022ac91fc9065b6ba0c3dfacc78097a5620101cd687902',
      o/'verilated_threads.o':'a7f51711612d60da9b567a6d6bd6f167e42c26c620e38252683ec1c9a98fbeb7',
      Path('tests/rocket_chiptop.cpp'):pin['inputs']['rocket_chiptop.cpp']}
for name in ['VChipTop__ALL.a','VChipTop___024root.h']:keys[o/name]=pin['models']['stock'][name]
keys[Path('tests/chiptop_address.hpp')]='1a79c1e91ac8f1b34e4922f5b9069115a19b7f1e53d36274a332bf17a50c2315'
keys[Path('tests/chiptop_debug.hpp')]='aaa4817843798f11cf68f41dcffc0c2dfde059cc7f79b7273ecf020f7e0be78f'
keys[Path('tests/chiptop_debug_slave.hpp')]='070f4c91a7ef46f329b12584093c2d65a0e0082bfce605c734c4a84b4b0da18b'
keys[Path('tests/chiptop_recovery.hpp')]='f44541458bb364bf1e0d5039562406530a5280fc6801ff7a79c08724a21e1cd9'
keys[Path('tests/chiptop_sba.hpp')]='ab2f34bd3025d4d0c012a7f48f3177e1a0b396207a3b10e183a0cb2717050417'
keys[Path('tests/chiptop_sd.hpp')]='a5f5d11134f1b40dadc7b58cd749d47e09dafd1fdda6f9ac25b1f6e7329f57d4'
for path,want in keys.items():
    if hashlib.sha256(path.read_bytes()).hexdigest()!=want:raise ValueError('unexpected model input: '+path.name)
PY
"${CXX:-g++}" -std=c++17 -O2 -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$obj" -I"$inc" -I"$inc/vltstd" tests/mega_user_replay.cpp "$obj/VChipTop__ALL.a" \
  "$obj/verilated.o" "$obj/verilated_threads.o" -pthread -latomic -o "$out/model"
sha256sum "$out/model" "$guest"/{performance,validation}/replay/{mem.bin,prefix.frame} \
  tests/{mega_user_replay.cpp,rocket_chiptop.cpp,chiptop_*.hpp} >"$out/inputs.sha256"
for seed in performance validation; do
  n=$(python3 -c 'import json,sys; print(json.load(open("docs/perf-strict-user-window.json"))["results"][sys.argv[1]]["dynamic_instructions"])' "$seed")
  d="$guest/$seed/replay"; "$out/model" "$d/mem.bin" "$d/prefix.frame" "$n" "$out/$seed.pc" >"$out/$seed.uart" 2>"$out/$seed.events"
done
sha256sum --quiet -c "$out/inputs.sha256"
python3 scripts/review-strict-user-replay.py "$out"
