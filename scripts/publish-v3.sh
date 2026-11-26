#!/usr/bin/env bash
# Publish the locally verified v3 candidate after two independent builds and guest tests.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; out=$root/artifacts; a=$out/staged-v3-a; b=$out/staged-v3-b
for d in "$a" "$b"; do (cd "$d" && sha256sum -c software.sha256); done
cmp "$a/software.sha256" "$b/software.sha256"; grep -q TWO_CLEAN_BUILD_DIRS_BYTE_IDENTICAL logs/repro-v3.txt; grep -q QEMU_STORAGE_PASS logs/storage-v3.txt; grep -q 'QEMU_VIRT_REPEATED_PASS runs=10' logs/staged-v3-ten-boots.txt
python3 - "$a" <<'PY'
from pathlib import Path
import hashlib,sys
p=Path(sys.argv[1]); b=(p/'fw_payload.bin').read_bytes(); d=(p/'vcu118-linux-data.img').read_bytes(); assert d[34*512:34*512+len(b)]==b and not any(d[34*512+len(b):34*512+(30<<20)])
PY
prev=$out/releases/v2; mkdir -p "$prev"
if [[ ! -s $prev/software.sha256 ]]; then
 [[ $(sha256sum "$out/fw_payload.bin" | cut -d' ' -f1) = 944cd518fa7ec81b017a2070e7d15a02f4dd7c37f1e697db3e32169c29907cda ]]; for f in Image kernel.config soc-check.elf fw_payload.bin vcu118-linux.img; do cp "$out/$f" "$prev/$f"; done; cp "$out/software.sha256" "$prev/"; cp logs/release-check.txt "$prev/release-check.txt"
fi
(cd "$prev" && sha256sum -c software.sha256); tmp=$(mktemp -d "$out/.publish.XXXXXX"); trap 'rmdir "$tmp" 2>/dev/null || :' EXIT
python3 scripts/make_sd.py "$a/fw_payload.bin" "$tmp/vcu118-linux.img"; sgdisk -v "$tmp/vcu118-linux.img" | tee logs/linux-v3-gpt.txt; grep -q 'No problems found' logs/linux-v3-gpt.txt
for f in Image kernel.config soc-check.elf fw_payload.bin vcu118-linux-data.img software.sha256; do cp "$a/$f" "$tmp/$f"; done
for f in fw_payload.bin Image kernel.config soc-check.elf vcu118-linux.img vcu118-linux-data.img software.sha256; do mv -f "$tmp/$f" "$out/$f"; done
python3 scripts/test-release.py | tee logs/release-check-v3.txt; echo RELEASE_V3_PUBLISHED
