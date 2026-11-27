#!/usr/bin/env bash
# Local RTL simulator, not a signoff kit and not for synthesis or publication.
set -euo pipefail
source "$(dirname "$0")/generator-env.sh"; cd "$root"
case ${VCU_BOOM_MODEL:-medium} in
 medium) cfg=PerfMediumBoomVCU118Config; overlay=PerfMediumBoom.scala;;
 no-fast-load) cfg=PerfNoFastLoadBoomVCU118Config; overlay=PerfNoFastLoadBoom.scala;;
 partial-mega) cfg=PerfPartialMegaBoomVCU118Config; overlay=PerfPartialMegaBoom.scala;;
 mega) cfg=PerfMegaBoomVCU118Config; overlay=PerfMegaBoom.scala;;
 large) cfg=PerfLargeBoomVCU118Config; overlay=PerfLargeBoom.scala;;
 *) echo 'unknown BOOM model' >&2; exit 2;;
esac
 name=chipyard.fpga.vcu118.VCU118FPGATestHarness.$cfg
gen=$cy/fpga/generated-src/$name; rom=$cy/fpga/src/main/resources/vcu118/sdboot/build/sdboot.elf
kit=${1:?fresh model kit directory}; obj=${2:?fresh object directory}; test ! -e "$obj"
python3 scripts/check-board-dt.py "$gen/$name.dts" --rom "$rom"
python3 - "$cy" "$gen" "$rom" "$kit" "$overlay" <<'PY'
from pathlib import Path
import hashlib, re, sys
cy,g,rom,kit=map(lambda v:Path(v).resolve(),sys.argv[1:5]); base=g.name
assert '"ucb-bar,boom0"' in (g/(base+'.dts')).read_text()
paths=[Path(line).resolve(strict=True) for line in (g/(base+'.vsrcs.f')).read_text().splitlines() if line.strip()]
assert len(paths)>300 and all(cy in p.parents and p.suffix in ('.v','.sv') for p in paths)
assert len({p.name for p in paths})==len(paths) and {'BoomCore.sv','BoomTile.sv','ChipTop.sv','TLROM.sv'} <= {p.name for p in paths}
assert len(re.findall(r'^\s*BoomCore\s+\w+\s*\(', (g/'gen-collateral'/'BoomTile.sv').read_text(),re.M))==1
kit.mkdir(); (kit/'rtl').mkdir(); (kit/'rom').mkdir(); files={}
def put(k,data):
 (kit/k).write_bytes(data); files[k]=hashlib.sha256(data).hexdigest()
for p in paths:put('rtl/'+p.name,p.read_bytes())
put('sources.f',''.join('rtl/'+p.name+'\n' for p in paths).encode());put('rom/sdboot.elf',rom.read_bytes());put('rom/sdboot.bin',rom.with_suffix('.bin').read_bytes());put('board.dts',(g/(base+'.dts')).read_bytes());put('config.scala',(Path('rtl/perf')/sys.argv[5]).read_bytes())
(kit/'CANDIDATE.sha256').write_text(''.join(f'{files[k]}  {k}\n' for k in sorted(files)));print('LOCAL_BOOM_MODEL_INPUTS',len(paths))
PY
VCU_SIM_KIT=$(realpath "$kit") VCU_SIM_OBJ="$obj" bash scripts/build-rtl-sim.sh
python3 scripts/check-model-kit.py "$obj" "$kit"
