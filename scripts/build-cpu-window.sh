#!/usr/bin/env bash
# Screen microarchitecture at small cycle count, NOT the timed POSIX board score.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=${1:?fresh directory}; mkdir "$out"; out=$(realpath "$out"); export LC_ALL=C
profile=${2:-control}; arch=rv64imac_zicsr; opts=(-O2)
case "$profile" in
 control) ;;
 boom-events) opts+=(-DVCU_BOOM_EVENTS=1);;
 o3) opts=(-O3);;
 o3-zb) opts=(-O3); arch=rv64imac_zba_zbb_zicsr;;
 o3-zb-lto) opts=(-O3 -flto -Wl,--undefined=memset); arch=rv64imac_zba_zbb_zicsr;;
 o3-zb-lto-unroll) opts=(-O3 -flto -funroll-loops -Wl,--undefined=memset); arch=rv64imac_zba_zbb_zicsr;;
 *) echo 'unknown diagnostic profile' >&2; exit 2;;
esac
bash scripts/fetch-image-sources.sh coremark
# Use only the sources from the freshly checksum-verified upstream archive.
mkdir "$out/src"; tar -xf cache/coremark-9d07b05523c16754a214a40224018a4ee908e091.tar.gz -C "$out/src" --strip-components=1
src=$out/src; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
case ${VCU_WINDOW_CC:-13} in
 13) cc=$tools/bootlin/bin/riscv64-linux-; version=13.3.0;;
 15) cc=$tools/bootlin-cpu-2025.08-1/bin/riscv64-linux-; version=15.1.0;;
 *) echo 'unrecognized compiler' >&2; exit 2;;
esac
test "$("${cc}gcc" -dumpfullversion)" = "$version"; "${cc}gcc" --version >"$out/compiler.txt"
make -C "$src" PORT_DIR=posix check
# Independent reference CRCs for four iterations, produced by the upstream POSIX main.
make -C "$src" PORT_DIR=posix CC=gcc ITERATIONS=0 OPATH="$out/" "$out/coremark.exe"
for test in performance validation; do seed=0; [[ $test != validation ]] || seed=0x3415
 "$out/coremark.exe" $seed $seed 0x66 4 7 1 2000 > "$out/host-$test.txt"
done
python3 - "$out" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); result=[]
for t,expected in [('performance',('e9f5','e714','1fd7','8e3a')),('validation',('18f2','e3c1','0747','8d84'))]:
 s=(p/f'host-{t}.txt').read_text(); assert f'2K {t} run parameters for coremark.' in s
 for key,val in zip(['seedcrc','[0]crclist','[0]crcmatrix','[0]crcstate'],expected): assert re.search('^'+re.escape(key)+r'\s*: 0x'+val+'$',s,re.M)
 crc,=re.findall(r'^\[0\]crcfinal\s*: (0x[0-9a-f]{4})$',s,re.M); result.append(f'#define EXPECTED_{t.upper()} {crc}u')
(p/'reference.h').write_text('\n'.join(result)+'\n')
PY
flags=("${opts[@]}" -ffunction-sections -fdata-sections -fno-pie -no-pie -fno-stack-protector -nostdlib -static -ffreestanding -fno-builtin -mcmodel=medany -march="$arch" -mabi=lp64 -I"$src/posix" -I"$src" -DFLAGS_STR='"diagnostic"' -DITERATIONS=4)
printf '%s\n' "$profile" "${flags[@]}" >"$out/build-flags.txt"
# GCC otherwise leaves its randomized temporary assembler object name in the
# ELF symbol table. A fixed basename preserves both code and reproducible ELF IDs.
"${cc}gcc" "${flags[@]}" -c software/bare/entry.S -o "$out/entry.o"
"${cc}gcc" "${flags[@]}" -include "$out/reference.h" -T software/bare/layout.ld -Wl,--gc-sections,--build-id=none "$out/entry.o" software/cpu-window/window.c "$src"/{core_list_join,core_main,core_matrix,core_state,core_util}.c -o "$out/window.elf"
"${cc}objcopy" -O binary "$out/window.elf" "$out/window.bin"; "${cc}objdump" -d "$out/window.elf" >"$out/disasm.txt"; "${cc}nm" -n "$out/window.elf" >"$out/symbols.txt"; if [[ $profile != *lto* ]]; then grep -q ' T iterate$' "$out/symbols.txt"; fi; grep -q '0000000080000000 T _start$' "$out/symbols.txt"
(cd "$out" && sha256sum window.bin window.elf > inputs.sha256); echo CPU_WINDOW_BUILT_NOT_A_SCORE
