#!/usr/bin/env python3
"""Inspect the actual firtool graph for a registered, two-entry A/D debug-slave cut."""
import argparse
import re
from pathlib import Path

COUPLER = 'TLInterconnectCoupler_cbus_to_debug'


def text(directory, name):
    src = (directory / (name + '.sv')).read_text()
    src = re.sub(r'//[^\n]*|/\*.*?\*/', '', src, flags=re.S)
    if len(re.findall(r'\bmodule\s+' + re.escape(name) + r'\s*\(', src)) != 1:
        raise ValueError(f'{name}: unexpected module declaration')
    return src


def instance(src, type_re, name):
    matches = re.findall(r'^\s*(' + type_re + r')\s+' + name + r'\s*\((.*?)\);', src, re.M | re.S)
    if len(matches) != 1:
        raise ValueError(f'expected one instance {name}, found {len(matches)}')
    module, body = matches[0]
    ports = {}
    for field in body.split(','):
        m = re.fullmatch(r'\s*\.(\w+)\s*\(\s*([^()]*)\s*\)\s*', field)
        if not m or m[1] in ports:
            raise ValueError(f'{name}: unsupported or repeated binding {field}')
        ports[m[1]] = m[2].strip()
    for signal in ('clock', 'reset'):
        require(ports.get(signal), signal, f'{name}.{signal}')
    return module, ports


def require(found, expected, label):
    if found != expected:
        raise ValueError(f'{label}: expected {expected!r}, got {found!r}')


def queue_state(src):
    # Verify there is no direct ready/valid bypass of the occupancy state.
    compact = re.sub(r'\s+', ' ', src)
    for name in ('wrap', 'wrap_1', 'maybe_full'):
        if not re.search(r'\breg ' + name + ';', compact):
            raise ValueError('missing queue state flop '+name)
    for stmt in ('wire ptr_match = wrap == wrap_1;', 'wire empty = ptr_match & ~maybe_full;',
                 'wire full = ptr_match & maybe_full;', 'assign io_enq_ready = ~full;',
                 'assign io_deq_valid = ~empty;'):
        require(compact.count(stmt), 1, stmt)


def compare(base, variant):
    ref = text(base, COUPLER); new = text(variant, COUPLER)
    if re.search(r'\bTLBuffer\w*\s+\w+\s*\(', ref):
        raise ValueError('comparator is not the unbuffered coupler')
    _, original = instance(ref, 'TLFragmenter_Debug', 'fragmenter')
    _, frag = instance(new, 'TLFragmenter_Debug', 'fragmenter')
    module, cut = instance(new, r'TLBuffer\w*', 'vcuDebugSlaveBuffer')
    buf = text(variant, module)
    # Include all request and response payloads emitted on the fragmenter output.
    prefix = 'auto_anon_out_'
    keys = {p[len(prefix):] for p in original if p.startswith(prefix)}
    # Extra, unused-at-the-slave fields remain on this internal edge after
    # buffering: firtool can no longer prune them across the FIFO memory.
    internal = {p[len(prefix):] for p in frag if p.startswith(prefix)}
    require(internal - keys, {'a_bits_param','a_bits_corrupt','d_bits_param',
            'd_bits_sink','d_bits_denied','d_bits_corrupt'}, 'extra internal fields')
    require({k for k in cut if k.startswith('auto_out_')}, {'auto_out_'+k for k in keys}, 'external buffer edge')
    if not keys <= internal: raise ValueError('missing fragmenter output fields')
    private = set()
    for suffix in sorted(internal):
        if suffix in keys:
            require(original[prefix+suffix], 'auto_fragmenter_anon_out_'+suffix, 'baseline '+suffix)
        net = frag[prefix+suffix]
        if net in private or not re.fullmatch(r'\w+', net) or not re.search(r'\bwire\s+(?:\[[^]]+\]\s+)?'+re.escape(net)+r'\s*;', new):
            raise ValueError('expected unique private wire for '+suffix+': '+net)
        private.add(net)
        require(cut.get('auto_in_'+suffix), net, 'buffer input '+suffix)
        if suffix not in keys: continue
        ext = cut.get('auto_out_'+suffix, '')
        if not re.fullmatch(r'auto_\w+_out_'+suffix, ext) or not re.search(r'\b(?:input|output)\s+(?:\[[^]]+\]\s+)?'+re.escape(ext)+r'\s*[,)]',new):
            raise ValueError('missing corresponding coupler port '+suffix+': '+ext)
    queues = []
    for ch, inst, enq, deq in [('a', 'nodeOut_a_q', 'in', 'out'), ('d', 'nodeIn_d_q', 'out', 'in')]:
        q, ports = instance(buf, r'Queue2_TLBundle'+ch.upper()+r'\w*', inst)
        for fn, side in [('enq',enq), ('deq',deq)]:
            for sig in ('ready','valid'):
                require(ports.get('io_'+fn+'_'+sig), f'auto_{side}_{ch}_{sig}', f'{inst}.{fn}_{sig}')
        queue_state(text(variant, q)); queues.append(q)
    return module, queues, len(keys)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('unbuffered', type=Path); p.add_argument('buffered', type=Path)
    a = p.parse_args(); module, queues, count = compare(a.unbuffered, a.buffered)
    print('DEBUG_SLAVE_REGISTERED_CUT', module, *queues, 'fragmenter_signals='+str(count))
