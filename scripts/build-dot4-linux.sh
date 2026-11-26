#!/usr/bin/env bash
# Variant only: create an isolated, pinned Linux tree and all-new object/release directories.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"; work=${1:?fresh build directory on Linux filesystem}; release=${2:?fresh output directory}; mkdir "$work"; mkdir "$release"; work=$(realpath "$work"); release=$(realpath "$release"); shared=${VCU_BUILD:-$HOME/.cache/vcu118-build}; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cross=$tools/bootlin/bin/riscv64-linux-
for s in linux busybox opensbi; do bash scripts/fetch-image-sources.sh "$s"; done
mkdir -p "$work/src/linux"; for s in busybox opensbi; do ln -s "$shared/src/$s" "$work/src/$s"; done
tar -xf cache/linux-6.6.65.tar.xz -C "$work/src/linux" --strip-components=1
cp software/dot4/{vcu_dot4.c,vcu_dot4_uapi.h} "$work/src/linux/drivers/misc/"; printf '\nobj-y += vcu_dot4.o\n' >> "$work/src/linux/drivers/misc/Makefile"
VCU_DOT4_ENABLE=1 VCU_BUILD="$work" VCU_IMAGE_OBJ="$work/obj" VCU_RELEASE_OUT="$release" bash scripts/build-image.sh
"${cross}nm" "$work/obj/kernel/vmlinux" > "$work/symbols.txt"; grep -E ' [tT] dot_(probe|ioctl|remove)$' "$work/symbols.txt" | tee "$release/driver-symbols.txt"; test "$(wc -l < "$release/driver-symbols.txt")" = 3
cp "$work/obj/init-stage/dot4-check" "$release/dot4-check"; python3 scripts/make_sd.py --compact "$release/fw_payload.bin" "$release/linux-dot4-compact.img"; (cd "$release" && sha256sum -c software.sha256 && sha256sum dot4-check driver-symbols.txt linux-dot4-compact.img > variant.sha256); echo DOT4_KERNEL_LINK_AND_IMAGE_PASS
