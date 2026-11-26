#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; mkdir -p "$native/host"
gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 software/soc-check.c -o "$native/host/soc-check"
"$native/host/soc-check" 0
if "$native/host/soc-check" -1; then exit 1; fi
if "$native/host/soc-check" 'xyz'; then exit 1; fi
echo HOST_SELFTEST_PASS
