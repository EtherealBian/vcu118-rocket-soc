#!/usr/bin/env bash
# Install only into private directories, from Ubuntu's indexed, versioned .debs.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cache="$root/cache/qemu-debs"; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; dest="$tools/qemu"; mkdir -p "$cache" "$dest"; cd "$cache"
mapfile -t packages < <(apt-get -s --no-install-recommends install qemu-system-misc | awk '$1=="Inst" {i=3;if ($i ~ /^\[/) i++; sub(/^\(/,"",$i); print $2"="$i}')
((${#packages[@]})) || { command -v qemu-system-riscv64; exit; }
apt-get download "${packages[@]}"
for f in ./*.deb; do dpkg-deb -x "$f" "$dest"; done
export LD_LIBRARY_PATH="$dest/usr/lib/x86_64-linux-gnu:$dest/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$dest/usr/bin/qemu-system-riscv64" --version
