#!/usr/bin/env bash
# Produces a compact generic OpenSBI + uncompressed Linux Image + built-in initramfs.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); native=${VCU_BUILD:-$HOME/.cache/vcu118-build}; tools=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}
for s in busybox linux opensbi; do bash "$root/scripts/fetch-image-sources.sh" "$s"; done
src=$native/src; obj=${VCU_IMAGE_OBJ:-$native/image}; release=${VCU_RELEASE_OUT:-$root/artifacts}; mkdir -p "$obj"/{bb,kernel,opensbi} "$release"; export LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH=1733011200 KBUILD_BUILD_TIMESTAMP='2024-12-01 00:00:00 UTC' KBUILD_BUILD_USER=vcu KBUILD_BUILD_HOST=builder KBUILD_BUILD_VERSION=1
dot4=${VCU_DOT4_ENABLE:-0}; case "$dot4" in 0) ;; 1) test -n "${VCU_BUILD:-}" && test -n "${VCU_IMAGE_OBJ:-}" && test -n "${VCU_RELEASE_OUT:-}" && test "$release" != "$root/artifacts" && cmp "$src/linux/drivers/misc/vcu_dot4.c" "$root/software/dot4/vcu_dot4.c" || { echo 'use build-dot4-linux.sh with isolated directories'; exit 2; } ;; *) exit 2;; esac
oscheck=${VCU_OSCHECK_ENABLE:-0}; case "$oscheck" in 0) ;; 1) [[ -n ${VCU_IMAGE_OBJ:-} && -n ${VCU_RELEASE_OUT:-} && "$obj" != "$native/image" && "$release" != "$root/artifacts" ]] || { echo 'use a separate object directory and release for oscheck'; exit 2; } ;; *) exit 2;; esac
cross=$tools/bootlin/bin/riscv64-linux-; test -x "${cross}gcc"; jobs=${JOBS:-4}
gcc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 "$root/software/soc-check.c" -o "$obj/host-check"; "$obj/host-check" 0
"${cross}gcc" -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -Os -static -s "$root/software/soc-check.c" -o "$obj/soc-check"
bb=(make -C "$src/busybox" O="$obj/bb" ARCH=riscv CROSS_COMPILE="$cross"); "${bb[@]}" allnoconfig
python3 - "$obj/bb/.config" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text()
opts='STATIC ASH SH_IS_ASH ASH_JOB_CONTROL FEATURE_SH_MATH SETSID CTTYHACK CAT ECHO LS MOUNT MKDIR SLEEP UNAME DMESG DD CMP SHA256SUM SYNC HEAD POWEROFF REBOOT'.upper().split()
for k in opts:
 s,n=re.subn(r'^(?:# CONFIG_'+k+r' is not set|CONFIG_'+k+r'=.*)$','CONFIG_'+k+'=y',s,flags=re.M)
 if not n: raise SystemExit('unknown BusyBox option: '+k)
s=s.replace('CONFIG_SH_IS_NONE=y','# CONFIG_SH_IS_NONE is not set'); p.write_text(s)
PY
"${bb[@]}" oldconfig </dev/null; "${bb[@]}" -j"$jobs"; test -s "$obj/bb/busybox"; grep -qx CONFIG_STATIC=y "$obj/bb/.config"
# gen_init_cpio preserves file mtimes even when KBUILD_BUILD_TIMESTAMP is set.
# Stage copies with known ownership (manifest fields) and mtimes; do not touch sources.
stage=$obj/init-stage; mkdir -p "$stage"; install -m755 "$root/software/init" "$stage/init"; install -m755 "$obj/bb/busybox" "$stage/busybox"; install -m755 "$obj/soc-check" "$stage/soc-check"; touch -d @"$SOURCE_DATE_EPOCH" "$stage"/{init,busybox,soc-check}
if [[ $dot4 == 1 ]]; then
  "${cross}gcc" -Os -Wall -Wextra -Werror -static -s "$root/software/dot4/check.c" -o "$stage/dot4-check"
  # Keep the baseline init byte-identical. An expected accelerator must not silently skip.
  python3 - "$stage/init" <<'DOTINIT'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(); key='# Lab-only'; assert s.count(key)==1
p.write_text(s.replace(key, '''/bin/dot4-check --if-present || { echo LINUX_DOT4_FAILED; exec /bin/sh -i; }
'''+key))
DOTINIT
  touch -d @"$SOURCE_DATE_EPOCH" "$stage"/{init,dot4-check}
fi
if [[ $oscheck == 1 ]]; then
  "${cross}gcc" -Os -Wall -Wextra -Werror -march=rv64gc -mabi=lp64d -static -s -Wl,--build-id=none "$root/software/oscheck/check.c" "$root/software/oscheck/exchange.S" -o "$stage/os-check"
  # Run after the regular memory self-test, but before the local shell is offered.
  sed -i '/^# Lab-only/i /bin/os-check || { echo LINUX_OSCHECK_FAILED; exec /bin/sh -i; }' "$stage/init"
  grep -q '^/bin/os-check ' "$stage/init"
  touch -d @"$SOURCE_DATE_EPOCH" "$stage"/{init,os-check}
fi
manifest=$obj/kernel/initramfs.list
{ for d in bin sbin proc sys dev tmp; do echo "dir /$d 0755 0 0"; done
  echo 'nod /dev/console 0600 0 0 c 5 1'; echo 'nod /dev/null 0666 0 0 c 1 3'; echo "file /init $stage/init 0755 0 0"; echo "file /bin/busybox $stage/busybox 0755 0 0"; echo "file /bin/soc-check $stage/soc-check 0755 0 0";
  if [[ $dot4 == 1 ]]; then echo "file /bin/dot4-check $stage/dot4-check 0755 0 0"; fi
  if [[ $oscheck == 1 ]]; then echo "file /bin/os-check $stage/os-check 0755 0 0"; fi
  for cmd in sh ash cat echo ls mount mkdir sleep uname dmesg dd cmp sha256sum sync head poweroff reboot setsid cttyhack; do echo "slink /bin/$cmd busybox 0777 0 0"; done; } > "$manifest"
k=(make -C "$src/linux" O="$obj/kernel" ARCH=riscv CROSS_COMPILE="$cross"); KCONFIG_ALLCONFIG="$root/software/kernel.fragment" "${k[@]}" allnoconfig
"$src/linux/scripts/config" --file "$obj/kernel/.config" --set-str INITRAMFS_SOURCE initramfs.list
"${k[@]}" olddefconfig
for cap in MMU RISCV_SBI FPU SIFIVE_PLIC SERIAL_SIFIVE_CONSOLE SERIAL_8250_CONSOLE BINFMT_ELF BINFMT_SCRIPT BLK_DEV_INITRD PROC_FS SYSFS DEVTMPFS MMC_SPI SPI_SIFIVE VFAT_FS EXT4_FS VIRTIO_BLK; do grep -qx "CONFIG_$cap=y" "$obj/kernel/.config" || { echo "missing required kernel option $cap"; exit 1; }; done
"${k[@]}" -j"$jobs" Image
image=$obj/kernel/arch/riscv/boot/Image
make -C "$src/opensbi" O="$obj/opensbi" PLATFORM=generic CROSS_COMPILE="$cross" FW_TEXT_START=0x80000000 FW_PAYLOAD_OFFSET=0x200000 FW_PAYLOAD_PATH="$image" -j"$jobs"
fw=$obj/opensbi/platform/generic/firmware/fw_payload.bin
python3 - "$fw" "$image" <<'PY'
from pathlib import Path
import sys
fw,k=(Path(p).read_bytes() for p in sys.argv[1:]); assert 0<len(fw)<=30*(1<<20); assert k[56:60]==b'RSC\x05' and fw[0x200000:0x200000+len(k)]==k
PY
cp "$fw" "$release/fw_payload.bin"; cp "$image" "$release/Image"; cp "$obj/kernel/.config" "$release/kernel.config"; cp "$obj/soc-check" "$release/soc-check.elf"
(cd "$release" && sha256sum fw_payload.bin Image kernel.config soc-check.elf > software.sha256); echo IMAGE_BUILD_OK
