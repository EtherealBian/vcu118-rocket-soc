#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cache="$root/cache"; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; mkdir -p "$cache" "$native/src"
fetch_src() {
    local name=$1 url=$2 outfile=$3
    local path="$cache/$outfile"
    if ! test -s "$path"; then curl -fLsS --retry 2 --connect-timeout 20 "$url" -o "$path.part" && mv "$path.part" "$path" || return 1; fi
    if [ -f "$root/sources.sha256" ]; then (cd "$cache" && grep -F "  $outfile" "$root/sources.sha256" | sha256sum -c -) || return 1; else return 3; fi
    if [ ! -e "$native/src/$name" ]; then local t; t=$(mktemp -d "$native/src/.staging.XXXXXX"); tar -xf "$path" --strip-components=1 -C "$t" && mv "$t" "$native/src/$name" || return 1; fi
}
case "$1" in
linux) fetch_src linux https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.65.tar.xz linux-6.6.65.tar.xz;;
busybox) fetch_src busybox https://busybox.net/downloads/busybox-1.36.1.tar.bz2 busybox-1.36.1.tar.bz2;;
opensbi) fetch_src opensbi https://codeload.github.com/riscv-software-src/opensbi/tar.gz/refs/tags/v1.5.1 opensbi-1.5.1.tar.gz;;
esac
