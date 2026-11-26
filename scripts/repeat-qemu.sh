#!/usr/bin/env bash
# Verify a prospective candidate without touching the current default release.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd);cd "$root"; : "${VCU_FIRMWARE:=$root/artifacts/fw_payload.bin}"; export VCU_FIRMWARE
n=${1:-10}; [[ $n =~ ^[1-9][0-9]*$ && $n -le 100 ]] || exit 2
run=$(mktemp -d "$root/logs/qemu-repeated.XXXXXX"); sha256sum "$VCU_FIRMWARE" > "$run/firmware.sha256"
for ((i=1;i<=n;i++)); do VCU_QEMU_LOG="${run#"$root/logs/"}/uart-$i.txt" python3 scripts/qemu-smoke.py | tee -a "$run/result.txt"; done
sha256sum -c "$run/firmware.sha256"; echo "QEMU_VIRT_REPEATED_PASS runs=$n evidence=$run" | tee -a "$run/result.txt"
