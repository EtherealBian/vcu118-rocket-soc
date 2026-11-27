"""Match one live Linux hart to the ROM of an independently reviewed bit.

A ROM hash or clock declaration cannot qualify a new physical build. The
public CLI accepts only a bit already in the benchmark hardware registry.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SYSFS = '/sys/firmware/devicetree/base/'
PROPERTIES = ('cpus/timebase-frequency', 'cpus/cpu@0/compatible',
              'soc/pbus_clock/clock-frequency')
MEGA_SEAL = 'b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'


def expected(contract):
    if contract == 'rocket100':
        uarch = 'sifive,rocket0'
        values = ((100000).to_bytes(4, 'big'), b'sifive,rocket0\x00riscv\x00',
                  (100000000).to_bytes(4, 'big'))
        return uarch, [sha256(v).hexdigest() for v in values]
    if contract == MEGA_SEAL:
        # No bit is registered for this contract until separately signed off.
        d = json.loads((ROOT/'docs/perf-mega175-linux-identity.json').read_bytes())
        if (d['board_input_seal'], d['dtb_only_sha256'], d['expected_uarch'],
                d['expected_online_cpu'], d['expected_hart']) != (
                contract, '2e3ba8cdce15eae801abdb22e76b344bbf9aa1e91510ecc0922a581bf5258237',
                'ucb-bar,boom0', '0', 0):
            raise ValueError('unexpected four-wide ROM identity')
        vals = [(175000).to_bytes(4, 'big'), b'ucb-bar,boom0\x00riscv\x00',
                (175000000).to_bytes(4, 'big')]
        hashes = [sha256(v).hexdigest() for v in vals]
        if d['live_property_sha256'] != dict(zip((SYSFS+p for p in PROPERTIES), hashes)):
            raise ValueError('wrong four-wide ROM property digests')
        return d['expected_uarch'], hashes
    raise ValueError('no pinned Linux machine contract')


def inspect(lines, session_pos, stop_pos, boot_nonce, nonce, contract):
    if not all(isinstance(s, str) and re.fullmatch('[0-9a-f]{14}', s) for s in (boot_nonce, nonce)):
        raise ValueError('need independently reviewed boot nonce and fresh test nonce')
    def unique(s):
        hits = [i for i, line in enumerate(lines) if line in (s, '# '+s)]
        if len(hits) != 1:
            raise ValueError('missing or repeated boot or machine marker')
        return hits[0]
    a = unique('CM_BOOT_'+boot_nonce+'_42_'+nonce)
    b = unique('CM_MACHINE_END_42_'+nonce)
    if not 0 <= session_pos < a < b < stop_pos <= len(lines):
        raise ValueError('misordered boot or machine witness')
    body = lines[a+1:b]
    uarch, hashes = expected(contract)
    for key, wanted in (('processor', '0'), ('hart', '0'), ('uarch', uarch)):
        values = [m[1] for row in body if (m := re.fullmatch(key+r'\s*:\s*(\S+)', row))]
        if body[:1] != ['0'] or values != [wanted]:
            label = 'Rocket CPU' if contract == 'rocket100' else 'BOOM CPU'
            raise ValueError('expected one online '+label+' and hart 0')
    wanted = [digest+'  '+SYSFS+name for digest,name in zip(hashes, PROPERTIES)]
    if [row for row in body if SYSFS in row] != wanted:
        raise ValueError('live device tree differs from reviewed clock or CPU')


if __name__ == '__main__':
    import sys
    import benchmark_hardware as hw
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('bit', 'boot_nonce', 'nonce', 'session'):
        p.add_argument(k)
    args = p.parse_args()
    if not re.fullmatch('[a-f0-9]{16}', args.session):
        p.error('expected matrix session tag')
    lines = sys.stdin.read().replace('\r','').splitlines()
    def at(marker):
        hits = [i for i,l in enumerate(lines) if l in (marker, '# '+marker)]
        if len(hits) != 1:
            raise ValueError('missing or repeated live/session marker')
        return hits[0]
    session_pos = at(f'CM_SESSION_{args.session}_42_{args.nonce}')
    if at('CM_LIVE_42_'+args.nonce) >= session_pos:
        raise ValueError('bad live/session order')
    inspect(lines, session_pos, len(lines), args.boot_nonce, args.nonce, hw.lookup(args.bit)['runtime_contract'])
    print('LIVE_MACHINE_MATCHES_REGISTERED_BIT_NOT_A_BENCHMARK')
