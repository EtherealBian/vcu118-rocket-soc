#!/usr/bin/env python3
"""Cross-check routed AW write-enable wires in two archived controls. Not STA."""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
import json
import mmap
from pathlib import Path
import re

DOCS = Path(__file__).resolve().parents[1] / 'docs'
TOP = 'VCU118FPGATestHarness'
AW = 'mig/axi4asource/nodeOut_aw_source/'
SHARED = 'mig/toaxi4/queue_arw_deq_q/widx_widx_bin[2]_i_2__1'
RX = 'mig/island/axi4asink/'
WORD = re.compile(r'mem_([0-7])_(\w+)_reg\[(\d+)\]')
NUMBER = r'\d+(?:\.\d+)?'
TRIPLE = rf'\(({NUMBER}):({NUMBER}):({NUMBER})\)'
ARC = re.compile(rf'\(INTERCONNECT (\S+) (\S+) {TRIPLE} {TRIPLE}\)')
# Archive order: timesim Verilog, SDF, candidate manifest, implementation filelist.
# Original native build logs tied each bit, timing export and run directory together.
EXPORTS = {
    'd77b13dbf75b4773e33ba48f7b177f320572cb62ffe8a9cd930ab196edd6f520': (
        'd204ae0d979ade29bfac7d962edfcdd66952d95628e6d4fcfa2863f30344bdeb',
        '3ac55cbbab5bea3b9281d590b6ee3b5a056853c57a3a3d5d408c0347a7b844f2',
        'e28f9b3cbadbff993bf9d0861776490e841e1b613dfc5bc81ed194b4c2db571e',
        '26740c5078a945d7644beb1d4da42154dadbf85dfa1b977d3b3017ce9eb15e1d'),
    '156fa7e878ee11eb1cd961e581cf66bc5925d2ee908bbf880c5bf896a38aace3': (
        '1c01026406c5bbb29fa9d83467c8999270617891b77e68b79f91de5da835117f',
        '91ccd7c0c9fc567e1b9edda55f10242fe97c9faab9566904815fae9f698b8dc4',
        'c4e81bec2143a33472f962cd2705ec9b3f2f8d8a7791966dbefcf27f10cf1b0c',
        'efb1847bf8992724041111c3e1fe12ca8dce66d93f1dcb02425331e038c9a47f')}


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def moved_pairs(path):
    # Use exact complete phases of the original four-wide run. Never infer a wire
    # from a similar instance name, array index, replica or a later optimization.
    ref = json.loads((DOCS/'perf-mega175-aw-physopt.json').read_bytes())
    text = path.read_bytes().replace(b'\r\n', b'\n')
    stage = text.split(b'\nVCU118_STAGE=place\n')
    need(len(stage)==2, 'missing or repeated placement stage')
    stage = stage[1].split(b'\nVCU118_STAGE=route\n', 1)[0]
    body = stage.split(b'\nCommand: phys_opt_design -directive Explore\n')
    need(len(body)==2, 'wrong physical optimization stage')
    body = body[1].split(b'\nphys_opt_design completed successfully\n')
    need(len(body)==2 and sha256(body[0]).hexdigest()==ref['physopt_body_lf_sha256'],
         'different or incomplete four-wide physical optimization')
    text = body[0].decode()
    rows = []
    for phase in (32, 33):
        name = f'Phase {phase} Critical Path Optimization'
        blocks = re.findall(r'^'+name+r'\n([\s\S]*?)\n'+name+r' \| Checksum: [0-9a-f]+$', text, re.M)
        need(len(blocks)==1, 'missing phase')
        rows.extend(re.findall(r'^INFO: \[Physopt 32-663\] Processed net (\S+)\.  Re-placed instance (\S+)$', blocks[0], re.M))
    pairs = [(c[len(AW):], n[len(AW):]) for n,c in rows if c.startswith(AW) and n.startswith(AW)]
    need(len(pairs)==len(dict(pairs))==ref['aw_unique_cells']==42 and all(WORD.fullmatch(c) for c,_ in pairs),
         'ambiguous placed cell/net pairs')
    return ref['physopt_body_lf_sha256'], dict(pairs)


def netlist(path):
    with path.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        mods = list(re.finditer(rb'^module AsyncQueueSource_AXI4BundleAW\r?$', mm, re.M))
        need(len(mods) == 1, 'expected one AW module')
        start = mods[0].end()
        end = mm.find(b'\nendmodule', start)
        need(end > start, 'truncated AW module')
        text = mm[start:end].decode('ascii')
    gates, flops = {}, {}
    pattern = r"^  (FDRE|LUT5)\s+(?:#\(\s*\.INIT\(32'h[0-9A-Fa-f]+\)\)\s+)?(\S+)\s+\(([^;]+)\);"
    for typ, name, ports in re.findall(pattern, text, re.M):
        pins = {p: n.strip().lstrip('\\') for p, n in re.findall(r'\.(\w+)\(([^)]+)\)', ports)}
        name = name.lstrip('\\')
        if typ == 'FDRE' and WORD.fullmatch(name):
            need(name not in flops and 'CE' in pins, 'duplicate bit or missing CE')
            flops[name] = pins
        elif typ == 'LUT5':
            need('O' in pins and pins['O'] not in gates, 'missing or duplicate LUT5 output')
            gates[pins['O']] = name
    need({p['CE'] for p in flops.values()} <= gates.keys(), 'missing Verilog enable driver')
    return {bit: gates[p['CE']] for bit,p in flops.items()}, flops


def sdf(path, moved):
    tags = (AW.encode(), SHARED.replace('[',r'\[').replace(']',r'\]').encode())
    types, inputs, shared_out = {}, {}, set()
    launches = {AW+c+'/Q' for c in moved}
    outputs = defaultdict(dict)
    rx_tag = b'(INSTANCE '+RX.encode()
    celltype = None
    h = sha256()
    with path.open('rb', buffering=1 << 20) as f:
        header = [f.readline() for _ in range(9)]
        h.update(b''.join(header))
        need({s.strip() for s in header} >= {b'(TIMESCALE 1ps)', b'(VERSION "2024.2")',
             f'(DESIGN "{TOP}")'.encode()}, 'wrong SDF design, units or version')
        for line in f:
            h.update(line)
            if b'(CELLTYPE ' in line:
                celltype = line.split(b'"')[1].decode()
                continue
            if not any(tag in line for tag in tags) and rx_tag not in line:
                continue
            s = line.strip().decode('ascii').replace('\\', '')
            if s.startswith('(INSTANCE '):
                name = s[10:-1]
                need(name not in types, 'duplicate cell')
                types[name] = celltype
            elif s.startswith('(INTERCONNECT '):
                m = ARC.fullmatch(s)
                need(m is not None, 'unparsed selected wire arc')
                src, dst = m[1], m[2]
                if src in launches:
                    need(dst not in outputs[src], 'duplicate payload output destination')
                    outputs[src][dst] = max(Decimal(m[5]), Decimal(m[8]))
                if src == SHARED+'/O':
                    need(dst not in shared_out, 'duplicate shared output arc')
                    shared_out.add(dst)
                if dst.startswith((AW, SHARED+'/')):
                    need(dst not in inputs, 'duplicate SDF destination')
                    inputs[dst] = (src, max(Decimal(m[5]), Decimal(m[8])))
    return types, inputs, shared_out, outputs, h.hexdigest()


def trace(flops, types, inputs, shared_out):
    words = defaultdict(dict)
    wires, shared_wires, decoder_inputs = [], [], set()
    seen_ce = {k for k in inputs if k.startswith(AW) and k.endswith('/CE') and WORD.fullmatch(k[len(AW):-3])}
    need(seen_ce == {AW+k+'/CE' for k in flops}, 'SDF/Verilog payload bits differ')
    for bit, gate in flops.items():
        slot, field, i = WORD.fullmatch(bit).groups()
        name = AW+gate
        src, ps = inputs[AW+bit+'/CE']
        need(types.get(AW+bit)=='FDRE' and types.get(name)=='LUT5' and src==name+'/O', 'SDF/Verilog driver mismatch')
        words[int(slot)][(field, int(i))] = name
        wires.append(ps)
    need(set(words)==set(range(8)), 'missing AW slot')
    bits = {('addr', i) for i in [0, *range(5, 31)]} | {('id', i) for i in range(4)} | {('len', i) for i in range(8)} | {('size', 0), ('size', 1)}
    selectors = set()
    for group in words.values():
        gates = set(group.values())
        need(set(group)==bits and len(gates)==1, 'different slot payload/enable')
        gate, = gates
        selectors.add(gate)
        pins = {gate+f'/I{p}' for p in range(5)}
        need(pins <= inputs.keys(), 'missing slot decoder pin')
        need({inputs[p][0] for p in pins} == {AW+f'widx_gray_reg[{j}]/Q' for j in range(4)} | {SHARED+'/O'},
             'not four pointer bits and the shared enable')
        pin, = [p for p in pins if inputs[p][0]==SHARED+'/O']
        decoder_inputs.add(pin)
        shared_wires.append(inputs[pin][1])
    need(len(selectors)==8 and types.get(SHARED)=='LUT3', 'shared stage or terminal selectors differ')
    # Do not equate other loads with unused logic or interpret LUT names as Boolean functions.
    need(decoder_inputs <= shared_out and len(shared_out)==17 and len(decoder_inputs)==8, 'shared output sink inventory')
    shared_inputs = {d for d in inputs if d.startswith(SHARED+'/')}
    need(shared_inputs=={SHARED+'/I'+str(i) for i in range(3)}, 'shared LUT input inventory')
    need(any(inputs[p][0]=='mig/toaxi4/queue_arw_deq_q/full_reg/Q' for p in shared_inputs), 'missing upstream queue input')
    def span(vals):
        return [str(min(vals)),str(max(vals))]
    return dict(slot_count=len(words), bits_per_slot=dict(sorted(Counter(f for f, _ in bits).items())),
                physical_ce_pins=len(flops), final_decoder='8 x LUT5',
                shared_driver='1 x LUT3 in upstream AXI ARW queue hierarchy',
                shared_output_sink_pins=len(shared_out), shared_output_slot_decoder_inputs=len(decoder_inputs),
                shared_to_decoder_wire_max_ps_range=span(shared_wires), decoder_to_ce_wire_max_ps_range=span(wires))


def trace_moves(moved, flops, types, outputs):
    # A Verilog escaped identifier ends in whitespace; an optional vector index
    # follows it. Preserve the bracketed portions of both identifier and index.
    def netname(s):
        return re.sub(r' +(?=\[\d+\]$)', '', s)
    sink_cells, wire_delays = set(), []
    for bit, net in moved.items():
        pins = flops.get(bit, {})
        need({p for p, value in pins.items() if netname(value)==net}=={'Q'},
             'placed pair does not uniquely match the archived flop output')
        sinks = outputs.get(AW+bit+'/Q', {})
        need(len(sinks)==1, 'unexpected payload Q fanout')
        dest, ps = next(iter(sinks.items()))
        cell, pin = dest.rsplit('/', 1)
        need(cell.startswith(RX) and re.fullmatch(r'I[0-5]',pin) and types.get(cell)=='LUT6',
             'different first physical sink for the payload Q')
        sink_cells.add(cell)
        wire_delays.append(ps)
    need(len(outputs)==len(moved) and wire_delays, 'incomplete moved-output sample')
    return dict(exact_net_and_cell_pairs_on_Q=len(moved), first_sink_pins_in_receive_LUT6s=len(wire_delays),
                distinct_receive_LUT6s=len(sink_cells), Q_to_first_sink_wire_max_ps_range=[str(min(wire_delays)),str(max(wire_delays))])


def bind(bit, identities):
    need(bit in EXPORTS and EXPORTS[bit]==identities, 'mixed or unknown archived exports')


def review(run, kit, expected_bit, moved):
    obj = run/'obj'
    stem = obj/TOP
    bit = digest(stem.with_suffix('.bit'))
    need(bit==expected_bit, 'wrong archived control bit')
    pins = json.loads((DOCS/'perf-mega175-aw-select.json').read_bytes())['input_sha256']
    filelist, manifest = run/'sources.windows.f', kit/'CANDIDATE.sha256'
    sources, sealed = filelist.read_text().splitlines(), manifest.read_text().splitlines()
    for name, sha in pins.items():
        matches = [p for p in sources if p.endswith('/'+name)]
        need(digest(kit/'rtl'/name)==sha and f'{sha}  rtl/{name}' in sealed and
             len(matches)==1 and matches[0].endswith('/'+kit.name+'/rtl/'+name), 'different AW source '+name)
    clocks = (obj/'report'/'routed-clocks.rpt').read_text()
    need(re.findall(r'^clk_out1_harnessSysPLL\s+([\d.]+)\s+\{', clocks, re.M)==['10.000'], 'unexpected CPU period')
    v = stem.with_suffix('.v')
    types, inputs, outs, q_out, sh = sdf(stem.with_suffix('.sdf'), moved)
    vh, mh, fh = digest(v), digest(manifest), digest(filelist)
    bind(bit, (vh, sh, mh, fh))
    enables, flops = netlist(v)
    return dict(bit_sha256=bit, verilog_sha256=vh, sdf_sha256=sh, manifest_sha256=mh, source_list_sha256=fh,
                routed_cpu_clock_period_ns='10.000', **trace(enables, types, inputs, outs),
                matched_four_wide_placed_names_in_this_control=trace_moves(moved, flops, types, q_out))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ('four_wide_log', 'rocket_run', 'rocket_kit', 'medium_run', 'medium_kit'):
        ap.add_argument(k, type=Path)
    a = ap.parse_args()
    rocket = json.loads((DOCS/'coremark-target-rocket-control.json').read_bytes())['boot']['bit_sha256']
    medium = json.loads((DOCS/'perf-medium-route.json').read_bytes())['bit_sha256']
    body_hash, moved = moved_pairs(a.four_wide_log)
    result = dict(scope='Historical routing controls only. Interconnect delays: larger of rising/falling MAX per wire, in ps. Not path slack, four-wide STA or a board benchmark.',
                  four_wide_placed_physopt_body_lf_sha256=body_hash,
                  rocket=review(a.rocket_run, a.rocket_kit, rocket, moved),
                  two_wide_boom_withheld_from_board=review(a.medium_run, a.medium_kit, medium, moved))
    print(json.dumps(result, indent=2))


if __name__=='__main__':
    main()
