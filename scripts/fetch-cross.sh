#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
base=https://toolchains.bootlin.com/downloads/releases/toolchains/riscv64-lp64d/tarballs
pkg=riscv64-lp64d--musl--stable-2024.05-1.tar.xz
# Use native ext4 for the executable toolchain and C: for all downloadable archives and exported artifacts.
tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
mkdir -p "$root/cache" "$tools/bootlin"
cd "$root/cache"
curl -fLsS --retry 2 "$base/${pkg%.tar.xz}.sha256" -o "$pkg.sha256"
if ! test -s "$pkg"; then curl -fLsS --retry 2 "$base/$pkg" -o "$pkg.part"; mv "$pkg.part" "$pkg"; fi
grep -F "  $pkg" "$root/sources.sha256" | sha256sum -c -
if ! test -x "$tools/bootlin/bin/riscv64-linux-gcc"; then tar xJf "$pkg" -C "$tools/bootlin" --strip-components=1; "$tools/bootlin/relocate-sdk.sh"; fi
"$tools/bootlin/bin/riscv64-linux-gcc" --version | head -1
