#!/usr/bin/env python3
"""Audit both four-wide builds at elaboration; only emit a footprint with a confirmed checkpoint."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
SHARED = runpy.run_path(str(HERE / 'review-boom-synth-footprint.py'))
SEALS = runpy.run_path(str(HERE / 'verify-mega-impl-inputs.py'))['seals']
RESET = runpy.run_path(str(HERE / 'review-mega-mig-sysrst.py'))['inspect']
TOP, digest, portable = (SHARED[k] for k in ('TOP', 'digest', 'portable'))
LIB = 'scripts/rt/data/unisim_comp.v'
DRIVER = ('b629e39591895a7aefab2ec164b6bc74cf0527c2fe7d10dea920742549a279bb',
          '71018179a3db6b0ad0265a03b337b52bd92abe9e391d353bee93e5cf2f8b9213')
STAGE = '\nVCU118_STAGE=synth\n'
BOUNDARY = re.compile(rb'(?m)^Finished Applying XDC Timing Constraints : [^\r\n]+\r?\n')
MOD = re.compile(r"^INFO: \[Synth (8-6157|8-6155|8-638|8-256)\] (done |)synthesizing module '([^']+)'(?: \([^()]+\))? \[([^\n]+):(\d+)\]$")
XDC = re.compile(r"^(Finished |)Parsing XDC File \[([^\]]+)\](?: for cell '([^']+)')?$")


def need(test, why):
    if not test:
        raise ValueError(why)


def fingerprint(items):
    return sha256(json.dumps(items, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def command(header, kit, run, driver, current):
    commands = re.findall(r'^# Command line +: .*? -source (\S+) -tclargs ([^\n]+)$', header, re.M)
    need(len(commands) == 1, 'missing/ambiguous invocation')
    wrapper, args = commands[0]
    expected = [kit, run] if current else [kit/'implement.tcl', kit/'sources.f', kit/'shell/xilinx/common/tcl', run]
    need(portable(wrapper) == portable(driver) and sha256(driver.read_bytes().replace(b'\r\n', b'\n')).hexdigest() == DRIVER[int(current)] and
         portable(args) == ' '.join(portable(x) for x in expected), 'foreign driver, implementation kit, or run')
    marker = '\nRECOVERY_SEALED_RECIPE_START\n# source [file join $kit implement.tcl]\n' if current else '\n# source $launcher\n'
    need(marker in header and '\n# Vivado v2024.2 (64-bit)\n' in header and '\n# SW Build 5239630 ' in header,
         'wrong wrapper or tool build')


def module_rows(text, ids):
    starts, finishes = Counter(), Counter()
    for line in text.splitlines():
        if 'synthesizing module ' not in line:
            continue
        m = MOD.fullmatch(line)
        need(m and portable(m[4]) in ids, 'unrecognized elaboration row or source outside this build')
        code, done, name, raw, line_no = m.groups()
        need(bool(done) == (code in ('8-6155', '8-256')), 'incorrect elaboration message pairing')
        key = (name, ids[portable(raw)][0], int(line_no), 'vhdl' if code in ('8-256', '8-638') else 'verilog')
        (finishes if done else starts)[key] += 1
    need(starts and starts == finishes and max(starts.values()) == 1, 'missing or unmatched module completion')
    return sorted(starts)


def constraints(text, ids):
    starts, finishes = [], []
    for line in text.splitlines():
        if not re.match(r'^(?:Finished )?Parsing XDC File ', line):
            continue
        m = XDC.fullmatch(line)
        need(m and portable(m[2]) in ids, 'foreign or malformed XDC record')
        (finishes if m[1] else starts).append((ids[portable(m[2])][0], m[3]))
    need(len(starts) == 15 and starts == finishes and len(set(starts)) == 15, 'incomplete XDC scopes or parsing order')
    return starts


def project_ip(run, kit, sources):
    project = run/(TOP+'.xpr'); root = ET.parse(project).getroot()
    need(portable(root.get('Path', '')) == portable(project), 'XPR refers to another run')
    opts = {e.get('Name'): e.get('Val') for e in root.findall('Configuration/Option')}
    need(opts.get('Part') == SHARED['PART'] and opts.get('IPRepoPath') == '$PPRDIR/obj/ip', 'different project device or IP source')
    fs, = root.findall("FileSets/FileSet[@Name='sources_1'][@Type='DesignSrcs']")
    paths = [e.attrib['Path'] for e in fs.findall('File')]
    need(all(s.startswith('$PPRDIR/') for s in paths), 'unbound XPR source')
    top_xci = ['harnessSysPLL/harnessSysPLL.xci','vcu118mig/vcu118mig.xci']
    ip = run/'obj/ip'
    need([(run/s[8:]).resolve() for s in paths] == [kit/s for s in sources]+[ip/s for s in top_xci], 'XPR differs from ordered HDL/PLL/MIG inputs')
    exts = {'.sv','.v','.vh','.vhd','.xci','.xdc','.elf'}
    parts = {p.relative_to(ip).as_posix():digest(p) for p in ip.rglob('*') if p.is_file() and p.suffix in exts}
    return dict(project_design_sources=len(paths), top_xci_sha256={k:parts[k] for k in top_xci},
                selected_file_counts=dict(sorted(Counter(Path(k).suffix for k in parts).items())),
                selected_names_and_bytes_sha256=fingerprint(parts))


def one(log, kit, run, driver, vivado, current, pair, complete):
    seal = pair['candidate_sha256' if current else 'stock_sha256']
    need(digest(kit/'CANDIDATE.sha256') == seal, 'wrong kit'); sealed = SEALS(kit)
    sources = (kit/'sources.f').read_text().splitlines()
    actual = (run/'sources.windows.f').read_text().splitlines()
    need(len(sources) == len(set(sources)) == pair['ordered_hdl'] and all(k in sealed for k in sources) and
         [portable(kit/k) for k in sources] == [portable(p) for p in actual], 'wrong synthesized HDL list')
    project = project_ip(run, kit, sources)
    raw = log.read_bytes()
    m = BOUNDARY.search(raw); need(m, 'no completed constraint application')
    prefix = raw[:m.end()]; header, stage = prefix.decode(errors='replace').replace('\r\n', '\n').split(STAGE)
    command(header, kit, run, driver, current)
    before, _ = stage.split('\nFinished RTL Elaboration :', 1)
    need(before.count('\nCommand: synth_design -top '+TOP+' -flatten_hierarchy rebuilt\n') == 1, 'wrong top or synthesis strategy')
    ip = run/'obj/ip'
    entries = [(kit/k, 'kit/'+k) for k in sealed]
    entries += [(p, 'ip/'+p.relative_to(ip).as_posix()) for p in ip.rglob('*') if p.is_file()]
    entries += [(vivado/LIB, 'tool/'+LIB)]
    ids = {portable(p): (label, p) for p, label in entries}; paths = dict((s, p) for p, s in entries)
    modules = module_rows(before, ids); xdc = constraints(stage, ids)
    touched = {k: digest(paths[k]) for k in sorted({row[1] for row in modules} | {row[0] for row in xdc})}
    need(all(not k.startswith('kit/') or sealed[k[4:]] == sha and (k[4:] in sources or k.endswith(('.xdc','.sdc')))
             for k, sha in touched.items()), 'source not in sealed HDL or constraints')
    summary = dict(kit_seal_sha256=seal, wrapper_lf_sha256=DRIVER[int(current)], log_prefix_bytes=len(prefix),
                   log_prefix_sha256=sha256(prefix).hexdigest(), ordered_hdl_sha256=sealed['sources.f'],
                   project_ip=project, elaborations=len(modules), vhdl_elaborations=sum(r[3]=='vhdl' for r in modules),
                   verilog_elaborations=sum(r[3]=='verilog' for r in modules),
                   module_source_line_map_sha256=fingerprint(modules),
                   elaborated_files=dict(sorted(Counter(k.split('/')[0] for k in {r[1] for r in modules}).items())),
                   ordered_xdc_scopes_sha256=fingerprint(xdc), constraint_files=len(xdc),
                   observed_input_names_and_hashes_sha256=fingerprint(touched))
    footprint = None
    if complete:
        # Do not accept a partial DCP, a previous stage, a different run directory, or a synthetic cell table.
        stage = raw.decode(errors='replace').replace('\r\n', '\n').split(STAGE)[1]
        need('\nVCU118_STAGE=opt\n' in stage, 'synthesis not complete; no candidate footprint')
        dcp = run/'obj/post_synth.dcp'
        counts, table_id = SHARED['completed_table'](stage.split('\nVCU118_STAGE=opt\n', 1)[0], dcp)
        mig = RESET(dcp)  # Internal XDC cites this run by path; reject copied DCP with a matching top/part.
        footprint = dict(checkpoint_sha256=mig['checkpoint_sha256'], cell_table_sha256=table_id,
                         primitive_counts=counts, sum_LUT1_to_LUT6=sum(counts['LUT'+str(i)] for i in range(1,7)),
                         serialized_mig_sys_rst=mig)
    return summary, modules, xdc, touched, footprint


def compare(stock, new, pair):
    need(stock[0]['project_ip'] == new[0]['project_ip'], 'different project-registered IP or generated inputs')
    base = stock[3]; candidate = new[3]; changed = {'kit/'+k: v for k,v in pair['changed'].items()}
    need(base.keys()==candidate.keys() and {k:candidate[k] for k in base if base[k]!=candidate[k]}==changed,
         'source inventory changed outside three optimizations')
    need(stock[2] == new[2], 'different constraint ordering or scopes')
    def names(rows):
        return Counter((name, file, lang) for name,file,_,lang in rows)
    a, b = names(stock[1]), names(new[1]); helper = ('VcuIntMissSlot', 'kit/rtl/IssueUnitCollapsing_2.sv', 'verilog')
    need(b == a+Counter({helper:1}), 'unexpected elaborated module delta')
    for path in changed:
        need((Path(path).stem, path, 'verilog') in a, 'optimized parent not actually elaborated')
    return dict(added_module=helper[0], added_in=helper[1], changed_observed_files=changed,
                identical_observed_files=len(base)-len(changed),
                identical_generated_ip_hdl_or_constraints=sum(k.startswith('ip/') for k in base),
                identical_tool_primitive_library_sha256=base['tool/'+LIB],
                identical_constraint_scopes_in_order=len(stock[2]))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('old_log','old_kit','old_run','old_driver','new_log','new_kit','new_run','vivado'):
        p.add_argument(n,type=lambda s: Path(s).resolve(strict=True))
    p.add_argument('--completed',action='store_true',help='require BOTH confirmed post-synth DCPs and compare full primitive tables')
    a=p.parse_args(); pair=json.loads((HERE.parent/'docs/perf-mega175-miss-select.json').read_bytes())['pair_input']
    old=one(a.old_log,a.old_kit,a.old_run,a.old_driver,a.vivado,False,pair,True)
    new=one(a.new_log,a.new_kit,a.new_run,HERE/'run-mega-route-recovery.tcl',a.vivado,True,pair,a.completed)
    previous=json.loads((HERE.parent/'docs/perf175-synth-footprint.json').read_bytes())['four_wide_split']
    need(old[0]['log_prefix_sha256']=='06cac3e683c9c02a774fd43cd9abf70234a31d8973bbeccf99c8f29796f5cc12', 'wrong archived log prefix')
    need(old[4]['checkpoint_sha256']==previous['post_synth_dcp_sha256'] and old[4]['cell_table_sha256']==previous['cell_table_sha256'], 'wrong archived comparison')
    result=dict(scope='Log-confirmed elaboration and constraint parse scopes, not routed timing, exception coverage, bitstream, or board performance.',
                archived=old[0],candidate=new[0],comparison=compare(old,new,pair))
    if a.completed:
        result['whole_soc_synthesis_only']=dict(archived=old[4],candidate=new[4],
            lut_primitive_delta=new[4]['sum_LUT1_to_LUT6']-old[4]['sum_LUT1_to_LUT6'])
    print(json.dumps(result,indent=2))
