"""Compare selected native reports; agreement (including on a violation) is not signoff."""
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
FPGA = runpy.run_path(str(HERE / 'review-fpga.py'))
CDC = runpy.run_path(str(HERE / 'inventory-cdc.py'))
COMMANDS = {
    'route-status.rpt': 'report_route_status',
    'full-timing.rpt': 'report_timing_summary -report_unconstrained',
    'check-timing.rpt': 'check_timing -verbose',
    'cdc.rpt': 'report_cdc -details',
    'routed-clocks.rpt': 'report_clocks',
    'routed-drc.rpt': 'report_drc',
}


def portable(path):
    return re.sub(r'^/mnt/([a-z])/', r'\1:/', str(path).replace('\\', '/').lower())


def section(body, name, next_name):
    parts = body.split('\n| ' + name + '\n')
    if len(parts) != 2 or parts[1].count('\n| ' + next_name + '\n') != 1:
        raise ValueError('missing/ambiguous ' + name)
    return parts[1].split('\n| ' + next_name + '\n')[0]


def signature(name, raw, path):
    text = raw.decode('utf-8').replace('\r\n', '\n')
    if name == 'route-status.rpt':  # Only original report without a command header.
        if text.splitlines()[:1] != ['Design Route Status']:
            raise ValueError('missing route status')
        FPGA['route'](text)
        return text.strip()

    chunks = re.split(r'^-{20,}[ \t]*\n', text, maxsplit=2, flags=re.M)
    if len(chunks) != 3:
        raise ValueError('incomplete report header')
    _, header, body = chunks
    fields = {}
    for line in header.splitlines():
        m = re.fullmatch(r'\| ([^:|]+?)\s*:\s*(.+?)\s*', line)
        if not m or m[1] in fields:
            raise ValueError('invalid/duplicate report header')
        fields[m[1]] = m[2]
    required = {'Tool Version', 'Date', 'Host', 'Command', 'Design', 'Device', 'Design State', 'Speed File'}
    if not required <= fields.keys():
        raise ValueError('incomplete report identity')
    cmd, sep, dest = fields['Command'].partition(' -file ')
    drc = name == 'routed-drc.rpt'
    if (not fields['Tool Version'].startswith('Vivado v.2024.2 ') or
            fields['Design'] != 'VCU118FPGATestHarness' or
            fields['Device'] != ('xcvu9p-flga2104-2L-e' if drc else 'xcvu9p-flga2104') or
            fields['Design State'] != ('Fully Routed' if drc else 'Physopt postRoute') or
            cmd != COMMANDS[name] or not sep or portable(dest) != portable(path.resolve())):
        raise ValueError('wrong tool, design, route state, command or source report path')
    for key in ('Host', 'Date', 'Command'):
        del fields[key]
    body = '\n'.join(line.rstrip() for line in body.splitlines()).strip()
    if name == 'full-timing.rpt':
        # Equal-slack paths need not be reported in the same order. Compare the
        # timer settings/corners and scoped global summary; CPU paths are bound separately.
        settings = section(body, 'Timer Settings', 'Report Methodology')
        summary = section(body, 'Design Timing Summary', 'Clock Summary')
        if 'Enable Multi Corner Analysis' not in settings:
            raise ValueError('missing timer settings')
        body = [settings, FPGA['timing'](summary)]
    elif name == 'check-timing.rpt':
        FPGA['check_io'](body, FPGA['counters'](body))
    elif name == 'cdc.rpt':
        CDC['inventory'](body)  # Confirm detail cardinality; compare all rows, not just critical ones.
    elif name == 'routed-clocks.rpt' and not all(s in body for s in ('Clock Report', 'Waveform', 'Sources', 'clk_out1_harnessSysPLL')):
        raise ValueError('missing routed clock inventory')
    elif drc and not all(s in body for s in ('Report DRC', 'Checks found:', '2. REPORT DETAILS')):
        raise ValueError('missing default DRC inventory')
    return json.dumps([fields, body], sort_keys=True, allow_nan=False)


def compare_reports(original, reopened):
    if original.resolve() == reopened.resolve():
        raise ValueError('distinct report directories required')
    results = {}
    for name in COMMANDS:
        pair = {}; hashes = []
        for key, folder in [('original', original), ('reopened', reopened)]:
            path = folder / name
            record = pair[key] = {}
            try:
                raw = path.read_bytes()
                record['sha256'] = sha256(raw).hexdigest()
                sig = signature(name, raw, path)
                digest = sha256(sig.encode()).hexdigest()
                record['compared_sha256'] = digest
                hashes.append(digest)
            except (OSError, ValueError) as exc:
                # Keep both sides' evidence, and examine the other reports too.
                record['error'] = type(exc).__name__ if isinstance(exc, OSError) else str(exc)
        pair['matches'] = len(hashes) == 2 and hashes[0] == hashes[1]
        results[name] = pair
    return results
