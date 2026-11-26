#!/usr/bin/env bash
# Software-only Linux bring-up profile. The default firmware and board ROM stay unchanged.
# Keep the base Linux Image intact, but make early UART output observable and bound page initialization.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
work=${1:?fresh OpenSBI object directory}; out=${2:?fresh firmware output directory}; image=$(realpath "${3:-artifacts/Image}")
for d in "$work" "$out"; do [[ ! -e $d ]] || { echo "exists: $d" >&2; exit 2; }; done
mkdir "$work"; mkdir "$out"; work=$(realpath "$work"); out=$(realpath "$out")
tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}; cross=$tools/bootlin/bin/riscv64-linux-; native=${VCU_BUILD:-$HOME/.cache/vcu118-build}
expected=f87e46a7a53fdf5f7835a65b76bd8781c3f9ff3573fbcf5b619895e8ae8b2a5c
printf '%s  %s\n' "$expected" "$image" | sha256sum -c -
cy=$root/third_party/chipyard; cfg=chipyard.fpga.vcu118.VCU118FPGATestHarness.RocketVCU118Config; dts=$cy/fpga/generated-src/$cfg/$cfg.dts
rom=$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf
python3 scripts/check-board-dt.py "$dts" --rom "$rom" >"$out/source-board.txt"; grep -F GENERATED_BOARD_DT_CONTRACT_PASS "$out/source-board.txt"
dtc -q -I dts -O dtb -o "$work/base.dtb" "$dts"; cp "$work/base.dtb" "$out/diagnostic.dtb"
args='earlycon console=ttySIF0,115200 mem=128M'; fdtput -t s "$out/diagnostic.dtb" /chosen bootargs "$args"
[[ $(fdtget -t s "$out/diagnostic.dtb" /chosen bootargs) == "$args" ]]
# Canonicalized views must match after removing just this one new property.
cp "$out/diagnostic.dtb" "$work/roundtrip.dtb"; fdtput -d "$work/roundtrip.dtb" /chosen bootargs
for name in base roundtrip; do dtc -q -s -I dtb -O dts -o "$work/$name.dts" "$work/$name.dtb"; done; cmp "$work"/{base,roundtrip}.dts
bash scripts/fetch-image-sources.sh opensbi
export SOURCE_DATE_EPOCH=1733011200 LC_ALL=C TZ=UTC
make -C "$native/src/opensbi" O="$work/obj" PLATFORM=generic CROSS_COMPILE="$cross" FW_TEXT_START=0x80000000 FW_PAYLOAD_OFFSET=0x200000 FW_PAYLOAD_FDT_OFFSET=0x2200000 FW_PAYLOAD_PATH="$image" FW_FDT_PATH="$out/diagnostic.dtb" -j"${JOBS:-2}"
fw=$work/obj/platform/generic/firmware/fw_payload; cp "$fw.bin" "$out/fw_payload.bin"; "${cross}nm" -n "$fw.elf" >"$work/firmware.nm"
python3 - "$work/firmware.nm" "$out/fw_payload.bin" "$image" "$out/diagnostic.dtb" "$(dirname "$image")/fw_payload.bin" <<'PY'
from pathlib import Path as P
import hashlib,re,sys
sym,fw,image,dtb,base=map(P,sys.argv[1:]); body=fw.read_bytes(); fdt=dtb.read_bytes(); kernel=image.read_bytes()
off=int(re.search(r'^([0-9a-f]+)\s+\w\s+fw_fdt_bin$',sym.read_text(),re.M)[1],16)-0x80000000
baseline=base.read_bytes(); assert hashlib.sha256(baseline).hexdigest()=='7a8f9932796747be2cd54390af7adf88ba5b156e54069884946185fef47b41c9'
assert baseline[0x200000:]==kernel+bytes(8), 'unexpected baseline payload or linker padding'
assert 0<=off<0x200000 and body[off:off+len(fdt)]==fdt and body[0x200000:]==baseline[0x200000:] and kernel[56:60]==b'RSC\x05'
print('DIAG128_PAYLOAD_VERIFIED embedded_dtb_offset='+hex(off)+' kernel_bytes='+str(len(kernel)))
PY
python3 scripts/make_sd.py --compact "$out/fw_payload.bin" "$out/diagnostic.img"
(cd "$out"; sha256sum fw_payload.bin diagnostic.dtb diagnostic.img > profile.sha256); echo DIAG128_BUILD_OK_NOT_A_BOOT_TEST
