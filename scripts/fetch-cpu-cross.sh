#!/usr/bin/env bash
# Optional, isolated compiler for CPU experiments. Never replaces the baseline SDK.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root/cache"
base=https://toolchains.bootlin.com/downloads/releases/toolchains/riscv64-lp64d/tarballs
pkg=riscv64-lp64d--musl--bleeding-edge-2025.08-1.tar.xz
sha=5100cea9083aa2339113a61a64f857d4c8c68981d0a973e8fa1cd918a06b4854
sdk=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/bootlin-cpu-2025.08-1
if ! test -f "$pkg"; then
 part=$(mktemp "$pkg.XXXXXX"); trap 'rm -f -- "$part"' EXIT
 curl --fail --location --silent --show-error --retry 2 "$base/$pkg" -o "$part"
 echo "$sha  $part" | sha256sum -c -; mv -n "$part" "$pkg"
fi
echo "$sha  $pkg" | sha256sum -c -
if ! test -s "$sdk/.vcu-sdk-archive"; then
 mkdir "$sdk"; tar -xJf "$pkg" -C "$sdk" --strip-components=1; "$sdk/relocate-sdk.sh"; printf '%s\n' "$sha" >"$sdk/.vcu-sdk-archive"
fi
test "$(cat "$sdk/.vcu-sdk-archive")" = "$sha"
"$sdk/bin/riscv64-linux-gcc" --version
