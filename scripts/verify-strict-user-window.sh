#!/usr/bin/env bash
# Verify rebuilt symbol ranges and an independent four-round native CRC oracle,
# then count the unchanged target Linux executable. All derived files are temporary.
set -euo pipefail
cd "$(dirname "$0")/.."
qemu=$(realpath "${1:?extracted Ubuntu qemu-riscv64}"); elf=$(realpath "${2:?strict release ELF}")
cc=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin-cpu-2025.08-1/bin/riscv64-linux-
archive=coremark-9d07b05523c16754a214a40224018a4ee908e091.tar.gz
(cd cache; grep -F "  $archive" ../sources.sha256 | sha256sum --check --status)
test "$("${cc}gcc" -dumpfullversion)" = 15.1.0
t=$(mktemp -d /tmp/vcu-strict-window.XXXXXXXX); [[ $(realpath "$t") == /tmp/vcu-strict-window.???????? ]] || exit 2; trap 'rm -rf -- "$t"' EXIT
mkdir "$t"/{src,rv,native}; tar -xf "cache/$archive" --strip-components=1 -C "$t/src"
# Retain the original embedded FLAGS_STR, removing -s only as a standalone compiler argument.
cat > "$t/cc" <<'WRAPPER'
#!/usr/bin/env bash
set -eu
args=(); for a do if [[ $a != -s ]]; then args+=("$a"); fi; done
exec "$REAL_CC" "${args[@]}"
WRAPPER
chmod +x "$t/cc"; export REAL_CC="${cc}gcc"
make -s -C "$t/src" PORT_DIR=posix check >&2
make -s -C "$t/src" PORT_DIR=posix OPATH="$t/rv/" ITERATIONS=0 CC="$t/cc" PORT_CFLAGS='-O3 -flto -mtune=generic-ooo -mstrict-align' XCFLAGS='-static -s -march=rv64gc -mabi=lp64d -Wl,--build-id=none' "$t/rv/coremark.exe" >&2
"${cc}strip" -s -o "$t/rv/stripped" "$t/rv/coremark.exe"; cmp "$elf" "$t/rv/stripped"
"${cc}nm" -nS "$t/rv/coremark.exe" > "$t/nm"
make -s -C "$t/src" PORT_DIR=posix OPATH="$t/native/" ITERATIONS=0 CC=gcc PORT_CFLAGS=-O2 "$t/native/coremark.exe" >&2
python3 - "$t/nm" "$t/native/coremark.exe" <<'PY'
import re,runpy,subprocess,sys
from pathlib import Path
m=runpy.run_path('scripts/profile-strict-user-window.py'); syms=Path(sys.argv[1]).read_text()
for start,end,name in m['SYMS']+[(m['CLOCK'],0x14814,'__clock_gettime')]:
    if not re.search(rf'^{start:016x} {end-start:016x} [tT] {name}$',syms,re.M): raise SystemExit('bad symbol bounds: '+name)
for name,(seed,*_) in m['CM']['CASES'].items():
    out=subprocess.check_output([sys.argv[2],seed,seed,'0x66','4','7','1','2000'],text=True)
    if m['ORACLE']['crc'](out,name,4)!=m['CRC4'][name]: raise SystemExit('bad native CRC')
PY
python3 scripts/profile-strict-user-window.py "$qemu" "$elf" "${cc}objdump"
