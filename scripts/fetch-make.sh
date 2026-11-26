#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"
n=make-4.4.1.tar.gz; cd "$root/cache"; if [[ ! -s $n ]]; then curl --fail --location --silent --show-error --connect-timeout 10 --max-time 120 --retry 2 https://ftp.gnu.org/gnu/make/$n -o "$n.part"; mv "$n.part" "$n"; fi
printf 'c8469a3713cbbe04d955d4ae4be23eeb  %s\n' "$n" | md5sum -c -
grep -F "  $n" "$root/sources.sha256" | sha256sum -c -
mkdir -p "$native/gnu-make"; tar xzf "$n" -C "$native/gnu-make" --strip-components=1; cd "$native/gnu-make"
./configure --prefix="$tools" --disable-nls --without-guile; /usr/bin/make -j4; install -Dm755 make "$tools/bin/make"; "$tools/bin/make" --version
