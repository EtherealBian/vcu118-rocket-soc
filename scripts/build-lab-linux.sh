#!/usr/bin/env bash
# Optional lab image: baseline plus OS checks, Dot4 platform driver/check, and an on-demand CPU benchmark.
# No automatic benchmark on boot. No changes to the baseline system or bitstream.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
VCU_COREMARK_ENABLE=1 VCU_OSCHECK_ENABLE=1 bash "$root/scripts/build-dot4-linux.sh" "${1:?new Linux-native build directory}" "${2:?new release directory}"
