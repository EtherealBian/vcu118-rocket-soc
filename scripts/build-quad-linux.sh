#!/usr/bin/env bash
# Isolated SMP kernel/initramfs; generic OpenSBI can also be tested on four-hart QEMU virt.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); work=${1:?fresh object directory}; out=${2:?fresh release directory}; mkdir "$work"; mkdir "$out"
VCU_QUAD_SMP=1 VCU_OSCHECK_ENABLE=1 VCU_COREMARK_ENABLE=1 VCU_COREMARK_AB=1 VCU_IMAGE_OBJ=$(realpath "$work") VCU_RELEASE_OUT=$(realpath "$out") bash "$root/scripts/build-image.sh"
