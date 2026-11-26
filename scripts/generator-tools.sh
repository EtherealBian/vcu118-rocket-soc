#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cache="$root/cache"; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; mkdir -p "$tools" "$cache"
case "$1" in
java) name=OpenJDK20U-jdk_x64_linux_hotspot_20.0.2_9.tar.gz; url=https://github.com/adoptium/temurin20-binaries/releases/download/jdk-20.0.2%2B9/$name; dir=jdk20;;
firtool) name=firrtl-bin-linux-x64.tar.gz; url=https://github.com/llvm/circt/releases/download/firtool-1.75.0/$name; dir=firtool;;
*) exit 2;;
esac
cd "$cache"; if ! test -s "$name"; then curl -LfSs --retry 2 "$url" -o "$name.part"; mv "$name.part" "$name"; fi
grep -F "  $name" "$root/sources.sha256" | sha256sum -c -
if [ ! -d "$tools/$dir" ]; then t=$(mktemp -d "$tools/.stage.XXXXXX"); tar -xzf "$name" --strip-components=1 -C "$t"; mv "$t" "$tools/$dir"; fi
find "$tools/$dir" \( -name 'firtool' -o -name 'java' \) -type f
