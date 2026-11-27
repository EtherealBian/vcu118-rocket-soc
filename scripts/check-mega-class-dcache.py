#!/usr/bin/env python3
"""Elaborate the real D-cache from each sealed kit and check MSHR port ownership."""
import argparse
import json
import re
from pathlib import Path
import runpy
import subprocess
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
LIB = runpy.run_path(str(HERE / 'verify-mega-impl-inputs.py'))
h, seals = LIB['h'], LIB['seals']
TOP, PARENT, CHILD = 'BoomNonBlockingDCache', 'BoomMSHRFile', 'BoomMSHR'


def need(ok, why):
    if not ok:
        raise ValueError(why)


def only(seq, label):
    xs = list(seq)
    need(len(xs) == 1, 'missing or duplicate '+label)
    return xs[0]


def port(inst, name, direction):
    p = only((p for p in inst.findall('port') if p.get('name') == name and p.get('direction') == direction), name)
    ref = only(p, name+' expression')
    need(ref.tag == 'varref', 'not a direct connection: '+name)
    return ref


def wiring(tree, alt):
    modules = {m.attrib['name']: m for m in tree.findall('netlist/module')}
    need(TOP in modules and PARENT in modules and CHILD in modules, 'missing cache hierarchy')
    top = modules[TOP]; parent = modules[PARENT]
    instance = only((i for i in top.findall('instance') if i.get('defName') == PARENT), PARENT)
    need(instance.get('name') == 'mshrs', 'wrong cache instance')
    for lane in range(2):
        label = f'io_req_{lane}_ready'
        need(port(instance, label, 'out').get('name') == '_mshrs_'+label, 'cache lane swapped')
    banks = {i.get('name'): i for i in parent.findall('instance') if i.get('defName') == CHILD}
    need(set(banks) == {'mshrs_'+str(j) for j in range(8)}, 'incomplete bank set')
    for j in range(8):
        bank = banks['mshrs_'+str(j)]
        for name in ('vcu_open', 'vcu_permitted'):
            if alt:
                need(port(bank, name, 'out').get('name') == f'{name}_{j}', 'bank readiness swapped')
            else:
                need(not any(p.get('name') == name for p in bank.findall('port')), 'unexpected class outputs in reference')
    return instance, banks


def run(base, candidate, tool, out):
    kits = [p.resolve(strict=True) for p in (base, candidate)]
    expected = json.loads((HERE.parent/'docs/perf-mega175-mshr-candidate.json').read_bytes())
    tag = subprocess.check_output([tool, '--version'], text=True).strip()
    need(tag.startswith('Verilator 5.022 '), 'unexpected Verilator version')
    need(not out.is_symlink() and not out.exists(), 'need a new output directory')
    out = out.resolve(); need(all(out not in k.parents and k not in out.parents for k in kits), 'overlapping output'); out.mkdir(mode=0o700)
    results = {}; manifests = []; closures = []; warnings = []
    std = (tool.parent.parent/'share/verilator/include/verilated_std.sv').resolve(strict=True)
    for alt, (label, kit) in enumerate(zip(('stock', 'class_local'), kits)):
        digest = h(kit/'CANDIDATE.sha256'); need(digest == expected[['base_sha256', 'candidate_sha256'][alt]], 'wrong physical kit')
        seal = seals(kit); files = (kit/'sources.f').read_text().splitlines(); need(len(set(files)) == len(files) == expected['ordered_hdl'] and h(kit/'sources.f') == expected['ordered_list_sha256'], 'wrong HDL inventory')
        d = out/label; d.mkdir(); xml = d/'dcache.xml'
        # RAM modules live in aggregate HDL. Resolve the complete sealed file order,
        # not an inferred library of files whose basenames happen to match modules.
        manifest = d/'inputs.f'; manifest.write_text(''.join(str(kit/n)+'\n' for n in files))
        cmd = [tool, '--xml-only', '--xml-output', xml, '--Mdir', d, '-DSYNTHESIS', '--top-module', TOP, '-Wno-fatal', '-f', manifest]
        with (d/'parser.log').open('xb') as f:
            subprocess.run(cmd, cwd=d, stdout=f, stderr=subprocess.STDOUT, check=True)
        records = []
        for line in (d/'parser.log').read_text().splitlines():
            if line.startswith('%'):
                m = re.fullmatch(r'%Warning-TIMESCALEMOD: (.+?):(\d+):(\d+): Timescale missing on this module as other modules have it \(IEEE 1800-2017 3.14.2.3\)', line)
                need(m is not None, 'unexpected diagnostic'); n = Path(m[1]).relative_to(kit).as_posix()
                need(n in files, 'diagnostic outside kit'); records.append((n, m[2], m[3]))
        need(len(records) == len(set(records)) == 146, 'timescale diagnostic set changed'); warnings.append(sorted(records))
        tree = ET.parse(xml).getroot(); locs = {}; parsed = {}
        for node in tree.findall('files/file'):
            raw = node.attrib['filename']; locs[node.attrib['id']] = raw
            if raw in ('<built-in>', '<command-line>', str(manifest), str(std)):
                continue
            path = Path(raw).resolve(strict=True); leaf = path.relative_to(kit).as_posix()
            need(leaf in files and h(path) == seal[leaf], 'unsealed input: '+leaf); parsed[leaf] = seal[leaf]
        need(set(parsed) == set(files), 'parser did not consume the pinned input set')
        closure = {}
        for module_node in tree.findall('netlist/module'):
            path = Path(locs[module_node.attrib['loc'].split(',')[0]]).resolve(strict=True)
            leaf = path.relative_to(kit).as_posix(); closure[leaf] = parsed[leaf]
        for module in (TOP, PARENT, CHILD):
            node = only((m for m in tree.findall('netlist/module') if m.get('name') == module), module)
            need(Path(locs[node.attrib['loc'].split(',')[0]]).resolve() == kit/'rtl'/(module+'.sv'), 'module source mismatch')
        instance, banks = wiring(tree, bool(alt)); controls = []
        for link, new, reason in [(port(instance, 'io_req_0_ready', 'out'), '_mshrs_io_req_1_ready', 'cache lane swapped')] + ([(port(banks['mshrs_7'], 'vcu_permitted', 'out'), 'vcu_permitted_6', 'bank readiness swapped')] if alt else []):
            before = link.attrib['name']; link.set('name', new)
            try:
                wiring(tree, bool(alt))
            except ValueError as exc:
                need(str(exc) == reason, 'unexpected negative control failure'); controls.append(reason)
            else:
                raise ValueError('bad wiring accepted')
            finally:
                link.set('name', before)
        wiring(tree, bool(alt)); manifests.append(seal); closures.append(closure)
        results[label] = dict(kit_sha256=digest, timescale_warnings=len(records), parsed_hdl=len(parsed), cache_source_files=len(closure), elaborated_modules=len(tree.findall('netlist/module')), mshr_instances=len(banks), lane_outputs=2, class_output_connections=16 if alt else 0, rejected=controls)
    need(warnings[0] == warnings[1], 'diagnostic sites differ')
    need(set(closures[0]) == set(closures[1]), 'cache dependency sets differ')
    need(set(manifests[0]) == set(manifests[1]), 'kit sets differ')
    for a,b in (closures, manifests):
        need({n:b[n] for n in a if a[n] != b[n]} == expected['changed'], 'source delta differs')
    return dict(scope='Static D-cache hierarchy and selected port ownership only; no simulation, whole-core equivalence, timing or score.', parser=tag, parser_sha256=h(tool), tool_std_sha256=h(std), cases=results)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('base', 'candidate', 'verilator', 'out'): ap.add_argument(key, type=Path)
    a = ap.parse_args(); result = run(a.base, a.candidate, a.verilator.resolve(strict=True), a.out)
    (a.out/'review.json').write_bytes((json.dumps(result, indent=2)+'\n').encode()); print(json.dumps(result, indent=2))
