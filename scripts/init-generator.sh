#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cy="$root/third_party/chipyard"
cd "$cy"
test "$(git rev-parse HEAD)" = 69eba860a352343e4ac6b6df0f3638a79a86ec78
export GIT_TERMINAL_PROMPT=0
git config --local submodule.fetchJobs 4
# The pinned Gemmini test tree references a non-public IBM software dependency.
# Not elaborated by RocketVCU118Config. Keep the Gemmini Scala sources pinned.
git submodule update --init generators/gemmini
git -C generators/gemmini submodule update --init software/gemmini-rocc-tests
git -C generators/gemmini/software/gemmini-rocc-tests config --local submodule.rocc-software.update none
# Upstream skips heavyweight descendants that aren't required for the FPGA harness.
bash scripts/init-submodules-no-riscv-tools.sh
bash "$root/scripts/verify-generator-sources.sh"
