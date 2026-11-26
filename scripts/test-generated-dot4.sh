#!/usr/bin/env bash
# Real Rocket MMIO execution. JTAG sets PC/args after preloading only the testbench's RAM.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
out=${1:?fresh results directory}; sw=$(realpath "${2:?built bare dot4 directory}"); linux=${3:-}
mkdir "$out"; out=$(realpath "$out"); export VCU_SIM_CONFIG=Dot4RocketVCU118Config
cfg=chipyard.fpga.vcu118.VCU118FPGATestHarness.$VCU_SIM_CONFIG; gen=$root/third_party/chipyard/fpga/generated-src/$cfg
rom=$root/third_party/chipyard/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf
unset VCU_SIM_KIT; : "${VCU_SIM_OBJ:?supply a separate object directory for Dot4}"
python3 scripts/check-board-dt.py "$gen/$cfg.dts" --rom "$rom" >"$out/board-dt.txt"; grep -F DOT4_DTS_MMIO_PASS "$out/board-dt.txt"
python3 scripts/package-rtl.py --config "$VCU_SIM_CONFIG" --out "$out/rtl.zip" >"$out/rtl-package.txt"
# Simulate the verified portable archive, rather than mutable generator outputs.
mkdir "$out/kit"; python3 -m zipfile -e "$out/rtl.zip" "$out/kit"; export VCU_SIM_KIT=$out/kit
bash scripts/build-rtl-sim.sh >"$out/build.txt" 2>&1; cp "$VCU_SIM_OBJ/VChipTop" "$out/sim"
dtb=$(nm -n "$out/kit/rom/sdboot.elf" | awk '$3=="dtb" {print "0x"$1}'); test -n "$dtb"
v=${VCU_TOOLS:-$HOME/.local/share/vcu118-tools}/verilator; export LD_LIBRARY_PATH="$v/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" VERILATOR_ROOT="$v/share/verilator"
sha256sum "$out/sim" "$out/rtl.zip" "$out/kit/rom/sdboot.elf" >"$out/inputs.sha256"
run_case() {
 local mode=$1 image=$2 payload=$3 limit=$4
 sha256sum "$image" "$payload" >>"$out/inputs.sha256"
 "$out/sim" "$image" "$mode" "$limit" "$payload" "$dtb" >"$out/$mode.uart" 2>"$out/$mode.model"
 grep -F "ROCKET_RTL_PASS mode=$mode " "$out/$mode.uart"
 echo "$mode" >"$out/$mode.ok"
}
run_case debug-dot4 "$sw/dot4.img" "$sw/dot4.bin" 25000000; echo DOT4_BARE_CHIPTOP_PASS
if [[ -n $linux ]]; then
 run_case debug-linux-dot4 "$linux/linux-dot4-compact.img" "$linux/fw_payload.bin" 3000000000
 echo DOT4_LINUX_CHIPTOP_PASS
fi
