#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; mkdir -p third_party cache logs artifacts
ref=69eba860a352343e4ac6b6df0f3638a79a86ec78
if [ ! -e third_party/chipyard ]; then git -c core.autocrlf=false clone --branch 1.13.0 --depth=1 https://github.com/ucb-bar/chipyard.git third_party/chipyard; fi
test "$(git -C third_party/chipyard rev-parse HEAD)" = "$ref" || { echo 'ref mismatch: refusing to overwrite existing checkout'; exit 1; }
