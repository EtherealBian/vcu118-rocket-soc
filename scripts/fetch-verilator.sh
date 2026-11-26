#!/usr/bin/env bash
# The same Verilator 5.022 and runtime libraries pinned by Chipyard's lean lock.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); p=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; mkdir -p "$p" "$root/cache"
lock="$root/third_party/chipyard/conda-reqs/conda-lock-reqs/conda-requirements-riscv-tools-linux-64-lean.conda-lock.yml"
for name in verilator libstdcxx-ng libgcc-ng libstdcxx libgcc libzlib; do
 read -r url sha < <(python3 - "$lock" "$name" <<'PY'
import re,sys
s=open(sys.argv[1]).read();m=re.search(r'^- name: '+re.escape(sys.argv[2])+r'\n(.*?)(?=^- name: |\Z)',s,re.S|re.M)
if m:print(re.search(r'^  url: (\S+)',m[1],re.M)[1],re.search(r'^    sha256: (\w+)',m[1],re.M)[1]);
else: print('skip -')
PY
 ); [[ $url != skip ]] || continue; f="$root/cache/${url##*/}"; if [[ ! -s $f ]]; then curl --retry 3 --fail -L -o "$f.part" "$url"; mv "$f.part" "$f"; fi
 echo "$sha  $f" | sha256sum -c -; case $f in *.conda) unzip -p "$f" 'pkg-*.tar.zst' | tar --zstd -xf - -C "$p";; *.tar.bz2) tar -xjf "$f" -C "$p";; *) exit 1;; esac
done
export LD_LIBRARY_PATH="$p/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" VERILATOR_ROOT="$p/share/verilator"; "$p/bin/verilator_bin" --version
