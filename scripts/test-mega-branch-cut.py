#!/usr/bin/env python3
"""Try moving the four-wide BOOM B1 tag decode across its existing register edge.

Derive the sequential cuts from the changed BoomCore bytes, keep B2's binary
readouts, check them with unconstrained inputs, then map both sides of the cut.
Nothing touches the live implementation or hardware.
"""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
SEALS = runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']
LOCK = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
CORE = 'rtl/BoomCore.sv'
UNIT = '815c0140d41682fafa4df0e9cfa6ae7d3138bdb63c6f7d29440b497409218b24'
MASKS = ('_b1_resolve_mask_T_6', '_b1_mispredict_mask_T_10')
ROLES = ('stock', 'decode', 'qualified', 'banked')
EXTRAS = {'stock': (), 'decode': ('tag',), 'qualified': ('res','mis'), 'banked': ('high','low','low_mis')}


def packed(bits):
    return '{'+', '.join(reversed(bits))+'}'


def digest(data):
    return sha256(data).hexdigest()


def lane(i):
    d = '_alu_exe_unit'+(f'_{i}' if i else '')+'_io_brinfo_'
    q = f'brinfos_{i}_'
    fields = ('uop_br_tag', 'valid', 'mispredict')
    return [d+f for f in fields], [q+f for f in fields]


def add_after(source, pattern, addition):
    rows = list(re.finditer('^'+pattern+r'[^\n]*\n', source, re.M))
    if len(rows) != 1:
        raise ValueError('expected a unique RTL edit site: '+pattern)
    i = rows[0].end()
    return source[:i]+addition+'\n'+source[i:]


def variant(src, role):
    if role == 'stock':
        return src
    if role not in ROLES or 'vcu_b1_' in src:
        raise ValueError('wrong source or unknown variant')
    names = [[], []]
    for i in range(4):
        (tag, valid, miss), (qt, qv, qm) = lane(i)
        base = f'vcu_b1_{i}_'
        # (additional register, width, input expression, correlated simulation init).
        words = []
        if role == 'banked':
            for label, bits, count, gate, qgate in [
                    ('high', '[4:2]', 5, f' & {valid} & ~_rob_io_flush_valid', f' & {qv}'),
                    ('low', '[1:0]', 4, '', ''), ('low_mis', '[1:0]', 4, ' & '+miss, ' & '+qm)]:
                width = 3 if label == 'high' else 2
                def word(t, g):
                    return packed([f"(({t}{bits} == {width}'d{k}){g})" for k in range(count)])
                words.append((label, count, word(tag, gate), word(qt, qgate)))
        else:
            regs = [('tag', "1'b1", "1'b1")] if role == 'decode' else [
                ('res', f'({valid} & ~_rob_io_flush_valid)', qv),
                ('mis', f'({valid} & ~_rob_io_flush_valid & {miss})', f'({qv} & {qm})')]
            for label, en, q_en in regs:
                words.append((label, 20, f"{{19'b0, {en}}} << {tag}", f"{{19'b0, {q_en}}} << {qt}"))
        decl, edge, init = [], [], []
        for label, width, data, initial in words:
            name = base+label
            decl.append(f'  reg [{width-1}:0] {name};')
            edge.append(f"    {name} <= {data};")
            init.append(f"        {name} = {initial};")
        src = add_after(src, r'  reg +'+qm+';', '\n'.join(decl))
        src = add_after(src, '    '+qm+' <= '+miss+';', '\n'.join(edge))
        src = add_after(src, '        '+qm+r' = _RANDOM\[', '\n'.join(init))
        if role == 'decode':
            names[0].append('('+base+'tag & {20{'+qv+'}})')
            names[1].append('('+base+'tag & {20{'+qv+' & '+qm+'}})')
        elif role == 'banked':
            for out, low in zip(names, ('low', 'low_mis')):
                out.append(packed([f'({base}high[{k//4}] & {base}{low}[{k%4}])' for k in range(20)]))
        else:
            names[0].append(base+'res')
            names[1].append(base+'mis')
    for out, terms in zip(MASKS, names):
        src, n = re.subn(r'(  wire \[19:0\] +'+out+r' = )[^;]+;', lambda m: m[1]+' | '.join(terms)+';', src)
        if n != 1:
            raise ValueError('did not replace exactly one 20-bit mask')
    return src


def cut(src, role, name='top'):
    # Extract the actual register declarations/D expressions and the contiguous B1 wire block.
    # Added edge assignments live next to the original free-running lane register (not in a new stage).
    clean = [s.partition('//')[0].strip() for s in src.splitlines()]
    i = next(i for i,s in enumerate(clean) if re.match(r'wire \[31:0\] +_GEN =', s))
    j = next(i for i,s in enumerate(clean) if re.match(r'wire +use_this_mispredict_1 =', s))
    block = clean[i:j]
    if len(block) != 18 or not all(s.startswith('wire ') and s.endswith(';') for s in block):
        raise ValueError('unexpected source cone')
    decl, nbs, saved, inputs = [], [], [], []
    for i in range(4):
        (tag, val, mis), q = lane(i)
        inputs += ['input [4:0] '+tag, 'input '+val, 'input '+mis]
        saved.extend(q)
        keys = q + [f'vcu_b1_{i}_'+t for t in EXTRAS[role]]
        captures = []
        for n in keys:
            reg = [s for s in clean if re.fullmatch(r'reg +(?:\[\d+:0\] +)?'+n+';', s)]
            nb = [s for s in clean if s.startswith(n+' <= ')]
            if len(reg) != 1 or len(nb) != 1:
                raise ValueError('unexpected register source: '+n)
            decl += reg
            nbs += nb
            captures.append(clean.index(nb[0]))
        # Assert actual generated placement, not merely the right expression somewhere in the module.
        r0 = clean.index('brinfos_0_uop_is_rvc <= _alu_exe_unit_io_brinfo_uop_is_rvc;')
        end = max(captures)
        if clean[r0-1] != 'always @(posedge clock) begin' or min(captures) < r0 or not all(
                re.fullmatch(r'\w+ <= [^;]+;', row) for row in clean[r0:end+1]):
            raise ValueError('lane capture is no longer unconditional at the shared positive edge')
    ports = ', '.join(['input clock', 'input _rob_io_flush_valid', *inputs, 'output [67:0] observed'])
    return (f'module {name}({ports});\n'+'\n'.join(decl+block)+'\nalways @(posedge clock) begin\n'+
            '\n'.join(nbs)+'\nend\nassign observed = {'+', '.join([*MASKS,*saved])+'};\nendmodule\n')


def miter(a, b):
    ports = ['input clk', 'input fl', 'input [19:0] tag', 'input [3:0] v', 'input [3:0] m', 'output ok']
    args = ', '.join(['clk', 'fl']+[x for i in range(4) for x in (f'tag[{5*i}+:5]', f'v[{i}]', f'm[{i}]')])
    return (a+b+'module top('+', '.join(ports)+');\nwire [67:0] x,y;\n'+
            f'original a({args}, x); candidate b({args}, y);\nassign ok = x==y;\nendmodule\n')


def invoke(tool, d, cmd):
    p = subprocess.run([tool, '-Q', '-T', '-p', cmd], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    (d/'tool.log').write_bytes(p.stdout)
    p.check_returncode()
    return p.stdout.decode()


def prove(out, name, base, derived, bad=False):
    d = out/name
    d.mkdir()
    raw = miter(base, derived).encode()
    (d/'check.v').write_bytes(raw)
    return raw, d, bad


def proofs(srcs, out, tool):
    base = cut(srcs['stock'], 'stock', 'original')
    variants = {n: cut(srcs[n], n, 'candidate') for n in ROLES[1:]}
    cases = [prove(out, n+'-proof', base, text) for n,text in variants.items()]
    # Mutate the full candidate, THEN re-extract. Each mutant must show an actual t=2 discrepancy.
    (tag, val, _), (qt, _, _) = lane(0)
    for n, old, new in [('ignore-flush', f'{val} & ~_rob_io_flush_valid)', val+')'),
                        ('wrong-lane', '<< '+tag+';', '<< '+lane(1)[0][0]+';'),
                        ('late-tag', '<< '+tag+';', '<< '+qt+';')]:
        lines = srcs['qualified'].splitlines(keepends=True)
        indices = [i for i,s in enumerate(lines) if 'vcu_b1_0_res <=' in s and old in s]
        if len(indices) != 1:
            raise ValueError('missing fault site')
        i = indices[0]
        lines[i] = lines[i].replace(old, new, 1)
        cases.append(prove(out, n, base, cut(''.join(lines), 'qualified', 'candidate'), True))
    records = {}
    for raw, d, bad in cases:
        log = invoke(tool, d, 'read_verilog -noautowire check.v; prep -top top -flatten; '
                     'sat -seq 2 -prove-skip 1 -prove ok 1 -show-inputs -show-outputs')
        marker = 'SAT proof finished - '+('model found: FAIL!' if bad else 'no model found: SUCCESS!')
        if log.splitlines().count(marker) != 1 or (bad and not re.search(r'^\s*2\s+\\ok\s+0\s+0\s+0\s*$', log, re.M)):
            raise ValueError('unknown proof outcome: '+d.name)
        records[d.name] = dict(result='counterexample' if bad else 'proved', miter_sha256=digest(raw))
    return records


def topology(module):
    """Count directed combinational primitive levels; do not use timing or packing weights."""
    ports = module['ports']
    sizes = {'clock': (1, 'clock'), '_rob_io_flush_valid': (1, 'flush')}
    for i in range(4):
        sizes.update(zip(lane(i)[0], [(5, 'tag'), (1, 'valid'), (1, 'miss')]))
    if set(ports) != set(sizes) | {'observed'}:
        raise ValueError('different mapping ports')
    terminals, gates, pending, ffs, counts = {}, {}, set(), [], Counter()

    def register(bit):
        if type(bit) is not int or bit in terminals or bit in gates:
            raise ValueError('aliased driver or constant on output')

    for name, (width, kind) in sizes.items():
        p = ports[name]
        if p['direction'] != 'input' or len(p['bits']) != width:
            raise ValueError('wrong input shape')
        for bit in p['bits']:
            register(bit)
            terminals[bit] = kind
    obs = ports['observed']
    if obs['direction'] != 'output' or len(obs['bits']) != 68 or len(set(obs['bits'])) != 68:
        raise ValueError('wrong observation bus')
    for c in module['cells'].values():
        t = c['type']
        counts[t] += 1
        lut = re.fullmatch('LUT([1-6])', t)
        if t == 'FDRE':
            ins, out = ('C','CE','R','D'), 'Q'
        elif lut:
            ins, out = ['I'+str(j) for j in range(int(lut[1]))], 'O'
        elif t in ('MUXF7','MUXF8','MUXF9'):
            ins, out = ('I0','I1','S'), 'O'
        else:
            raise ValueError('unexpected primitive: '+t)
        edges = c['connections']
        expect = dict.fromkeys(ins, 'input'); expect[out] = 'output'
        if (c['port_directions'] != expect or set(edges) != set(expect) or
                any(len(v) != 1 for v in edges.values())):
            raise ValueError('unexpected primitive pinout')
        o = edges[out][0]
        register(o)
        if t == 'FDRE':
            if ((edges['C'], edges['CE'], edges['R']) != (ports['clock']['bits'], ['1'], ['0']) or
                    any(int(v, 2) for k,v in c.get('parameters', {}).items() if k.startswith('IS_') and k.endswith('_INVERTED'))):
                raise ValueError('different register clock, enable or reset')
            terminals[o] = 'Q'
            ffs.append(edges['D'][0])
        else:
            gates[o] = [edges[k][0] for k in ins]

    @lru_cache(None)
    def cone(n):
        if n in ('0','1'):
            return {'const': 0}
        if n in terminals:
            return {terminals[n]: 0}
        if n in pending or n not in gates:
            raise ValueError('combinational cycle or undriven net')
        pending.add(n)
        result = {}
        for child in gates[n]:
            for kind, distance in cone(child).items():
                result[kind] = max(result.get(kind, 0), distance+1)
        pending.remove(n)
        return result

    for n in gates:
        cone(n)
    upstream = [cone(n) for n in ffs]
    kinds = ('tag', 'valid', 'miss', 'flush')
    if not ffs or any(not(set(c) & set(kinds)) or set(c)-set(kinds)-{'const'} for c in upstream):
        raise ValueError('FF data is not an input cone')
    # observed concatenates {resolve, mispredict, binary}; JSON bits are LSB first.
    binary, mis, res = (obs['bits'][:28], obs['bits'][28:48], obs['bits'][48:])
    if any(terminals.get(n) != 'Q' for n in binary):
        raise ValueError('binary readout no longer driven directly by register')

    def distribution(bits):
        result = Counter()
        for n in bits:
            c = cone(n)
            if 'Q' not in c or set(c)-{'Q','const'}:
                raise ValueError('mask input bypasses register or has no register driver')
            result[c['Q']] += 1
        return dict(sorted(result.items()))

    return dict(cells=dict(sorted(counts.items())), input_to_D_max={k:max(c[k] for c in upstream if k in c) for k in kinds},
                Q_to_mispredict_levels=distribution(mis), Q_to_resolve_levels=distribution(res))


def seal_decode(kit, old, out, core):
    dst = out/'decode-physical-input'
    ordered = (kit/'sources.f').read_text().splitlines()
    if len(old) != 589 or len(ordered) != 549 or set(ordered) != {n for n in old if n.startswith('rtl/')}:
        raise ValueError('different compilation order or kit members')
    shutil.copytree(kit, dst)
    (dst/CORE).write_bytes(core)
    new = {n:digest((dst/n).read_bytes()) for n in old}
    if {n for n in old if old[n] != new[n]} != {CORE}:
        raise ValueError('not a one-module change')
    manifest = 'CANDIDATE.sha256'
    (dst/manifest).write_bytes(''.join(f'{h}  {n}\n' for n,h in sorted(new.items())).encode())
    if SEALS(dst) != new:
        raise ValueError('unexpected derived physical inputs')
    return dst, dict(kit_sha256=digest((dst/manifest).read_bytes()), changed={CORE:new[CORE]},
                     sealed_members=len(old), ordered_hdl_count=len(ordered), ordered_hdl_sha256=old['sources.f'])


def lint_pair(kit, dst, out, verilator):
    # Parse the entire changed module with real child interfaces and empty child bodies;
    # this does not compile or simulate the coupled core, or touch resources in Vivado.
    v = shutil.which(verilator)
    if not v:
        raise ValueError('need the configured verilator_bin executable for interface lint')
    v = str(Path(v).resolve(strict=True))
    version = subprocess.check_output([v, '--version']).decode().strip()
    signatures, records = {}, {}
    for role, root in [('stock',kit), ('decode',dst)]:
        src = (root/CORE).read_bytes().decode()
        types = re.findall(r'^  (\w+) +\w+ \(', src, re.M)
        if len(set(types)) != 19 or len(types) != 23:
            raise ValueError('unexpected direct children')
        headers = []
        for t in sorted(set(types)):
            text = (root/'rtl'/(t+'.sv')).read_bytes().decode()
            matches = re.findall(r'^module '+t+r'\(.*?^\);', text, re.M|re.S)
            if len(matches) != 1:
                raise ValueError('unexpected child declaration: '+t)
            headers.append(matches[0]+'\nendmodule\n')
        d = out/('lint-'+role); d.mkdir()
        child = ''.join(headers).encode(); (d/'interfaces.sv').write_bytes(child)
        for macro in ('SYNTHESIS', 'RANDOMIZE_REG_INIT'):
            # No -y library path: failure rather than loading the original BoomCore instead.
            args = [v, '--lint-only', '--top-module', 'BoomCore', '-Wno-fatal', '-D'+macro,
                    '--Mdir','obj-'+macro,str(root/CORE),'interfaces.sv']
            proc = subprocess.run(args,cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            (d/(macro+'.log')).write_bytes(proc.stdout); proc.check_returncode()
            log = proc.stdout.decode(); warnings = []
            for line in log.splitlines():
                if not line.startswith('%'):
                    continue
                m = re.fullmatch(r'%Warning-(\w+): .*BoomCore\.sv:\d+:\d+: (.+)',line)
                if not m:
                    raise ValueError('unknown diagnostic: '+line)
                warnings.append(m.groups())
            warnings = sorted(warnings)
            sig = (digest(child), warnings)
            if role == 'stock':
                signatures[macro] = sig
            if signatures[macro] != sig:
                raise ValueError('candidate changed lint diagnostics or child interfaces')
            records[macro] = dict(warnings=dict(sorted(Counter(k for k,_ in warnings).items())),
                                  messages_sha256=digest(json.dumps(warnings, separators=(',',':')).encode()))
    return dict(scope='Complete stock/decode BoomCore syntax and port binding against empty direct child interfaces only.',
                verilator_version=version, executable_sha256=digest(Path(v).read_bytes()), child_interfaces=len(set(types)),
                child_instances=len(types), interfaces_sha256=digest(child), modes=records)


def run(kit, out, tool, verilator):
    kit = kit.resolve(strict=True)
    out = out.resolve()
    if kit == out or kit in out.parents:
        raise ValueError('output inside sealed input')
    old = SEALS(kit)
    if digest((kit/'CANDIDATE.sha256').read_bytes()) != LOCK or old.get(CORE) != UNIT:
        raise ValueError('requires the original sealed four-wide physical inputs')
    stock = (kit/CORE).read_bytes()
    if digest(stock) != UNIT:
        raise ValueError('unexpected BoomCore read')
    abc = shutil.which('berkeley-abc')
    y = shutil.which(tool)
    if not abc or not y:
        raise ValueError('need yosys and berkeley-abc in the selected tool environment')
    y = str(Path(y).resolve(strict=True))
    out.mkdir()
    srcs = {r:variant(stock.decode(), r) for r in ROLES}
    sat = proofs(srcs, out, y)
    version = subprocess.check_output([y, '-V']).decode().strip()
    cmd = 'read_verilog -noautowire cut.v; synth_xilinx -top top -family xcup -flatten; check -assert; write_json mapped.json'
    result = {}
    for r,src in srcs.items():
        d = out/r; d.mkdir()
        raw = cut(src, r).encode()
        (d/'BoomCore.sv').write_bytes(src.encode())   # Private, never overwrite the active kit.
        (d/'cut.v').write_bytes(raw)
        log = invoke(y, d, cmd)
        net = json.loads((d/'mapped.json').read_bytes())
        if net['creator'] != version or log.splitlines().count('Running ABC command: berkeley-abc -s -f <abc-temp-dir>/abc.script 2>&1') != 1:
            raise ValueError('unidentified mapping toolchain')
        result[r] = dict(core_sha256=digest(src.encode()), cut_sha256=digest(raw), **topology(net['modules']['top']))
    selected = (out/'decode'/'BoomCore.sv').read_bytes()
    if digest(selected) != result['decode']['core_sha256'] or selected != srcs['decode'].encode():
        raise ValueError('mapped and sealed module differ')
    dst, candidate = seal_decode(kit, old, out, selected)
    lint = lint_pair(kit, dst, out, verilator)
    if (SEALS(kit) != old or digest((kit/'CANDIDATE.sha256').read_bytes()) != LOCK or
            SEALS(dst) != {**old, CORE:result['decode']['core_sha256']} or
            digest((dst/'CANDIDATE.sha256').read_bytes()) != candidate['kit_sha256']):
        raise ValueError('input or candidate changed during experiment')
    report = dict(scope='Isolated B1 register cut only. No placement, route, CPU timing, hardware or benchmark result.',
                  stock_kit_sha256=LOCK, yosys_version=version, yosys_elf_sha256=digest(Path(y).read_bytes()),
                  abc_elf_sha256=digest(Path(abc).read_bytes()), mapping_command=cmd, proofs=sat, mapping=result, decode_candidate=candidate, interface_lint=lint)
    (out/'summary.json').write_bytes((json.dumps(report, indent=2, sort_keys=True)+'\n').encode())
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kit', type=Path); p.add_argument('new_private_output', type=Path)
    p.add_argument('--yosys', default='yosys'); p.add_argument('--verilator', default='verilator_bin'); a = p.parse_args()
    run(a.kit, a.new_private_output, a.yosys, a.verilator)
