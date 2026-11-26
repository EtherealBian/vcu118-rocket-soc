#!/usr/bin/env bash
# Optional Linux workload; keep the baseline release and its evidence unchanged.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
obj=${1:?new native object directory}; out=${2:?new release directory}; mkdir "$obj"; mkdir "$out"
export VCU_OSCHECK_ENABLE=1 VCU_IMAGE_OBJ=$(realpath "$obj") VCU_RELEASE_OUT=$(realpath "$out")
bash scripts/build-image.sh
test -s "$VCU_IMAGE_OBJ/init-stage/os-check"
sha256sum "$VCU_IMAGE_OBJ/init-stage/os-check" | cut -d' ' -f1 > "$VCU_RELEASE_OUT/os-check.sha256"
echo OSCHECK_VARIANT_BUILT_NOT_TESTED
