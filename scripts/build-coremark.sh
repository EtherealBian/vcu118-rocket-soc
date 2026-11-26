#!/usr/bin/env bash
# Build the unmodified upstream POSIX port. Do not run or publish host timing as a board result.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); out=${1:?fresh output directory}; profile=${2:-baseline}; opt=-O2; arch=rv64gc
case "$profile" in baseline) ;; o3) opt=-O3;; o3-zb) opt=-O3; arch=rv64gc_zba_zbb;; *) echo "unknown profile" >&2; exit 2;; esac
 mkdir "$out"; out=$(realpath "$out")
native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cc=$tools/bootlin/bin/riscv64-linux-
bash "$root/scripts/fetch-image-sources.sh" coremark
src=$native/src/coremark
# Check against the same pinned archive, including the POSIX port and Makefile.
mkdir "$out/reference"; tar -xf "$root/cache/coremark-9d07b05523c16754a214a40224018a4ee908e091.tar.gz" --strip-components=1 -C "$out/reference"
for f in core_{list_join,main,matrix,state,util}.c coremark.h Makefile coremark.md5 posix/core_portme.{c,h,mak}; do cmp "$out/reference/$f" "$src/$f"; done
make -C "$src" PORT_DIR=posix check
# One context, default malloc method and POSIX clock_gettime; no PGO or source tuning.
make -C "$src" PORT_DIR=posix OPATH="$out/" ITERATIONS=0 CC="${cc}gcc" PORT_CFLAGS="$opt" XCFLAGS="-static -s -march=$arch -mabi=lp64d -Wl,--build-id=none" "$out/coremark.exe"
"${cc}readelf" -lW "$out/coremark.exe" > "$out/program.txt"; if grep -q INTERP "$out/program.txt"; then exit 1; fi
"${cc}gcc" --version | head -1 > "$out/compiler.txt"; (cd "$out" && sha256sum coremark.exe > elf.sha256)
echo COREMARK_BUILT_NOT_BENCHMARKED
