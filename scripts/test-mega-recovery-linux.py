#!/usr/bin/env python3
"""Cold-boot the sealed recovery ChipTop with the same Linux shell observer as stock."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import secrets
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
R = runpy.run_path(str(HERE/'test-mega-recovery-fullcore.py'))
S = runpy.run_path(str(HERE/'test-mega-linux-shell.py'))
F, need = R['F'], R['need']
h, doc, write = F['digest'], F['doc'], F['write']
ENTRY = 'perf-mega175-linux-entry.json'
PREVIOUS = 'perf-mega175-recovery-fullcore.json'
BENCH = 'coremark-g15-gc-lto-ooo-strict.elf'
# The observer is identical to the one already running on the stock model.
OBSERVER = {'boot.cpp':'4d886a3b36c0e207a710a4192660df8f592f24ec8b566fc4b7254bab0331d2e8',
            'mega_linux_shell.hpp':'2524b38e11795ba62d676f93d2742676a2f5ff6a16f98310084342170efda1d8'}


def qualified(physical, kit, previous, vt):
    ref = doc(PREVIOUS); obj = previous/'obj'; lock = previous/'inputs.json'
    need(h(lock) == ref['inputs_sha256'] and json.loads((previous/'result.json').read_bytes()) == ref,
         'not the previously reviewed candidate object directory')
    pins = json.loads(lock.read_bytes()); seal = R['PAIR'][1]
    need(h(physical/'CANDIDATE.sha256') == h(kit/'CANDIDATE.sha256') == pins['CANDIDATE.sha256'] ==
         ref['pair']['candidate_sha256'] == seal, 'not the exact recovery board input')
    need(R['I']['seals'](physical) == R['I']['seals'](kit), 'board and model kits differ')
    F['check_translation'](kit, obj)
    keys = (*F['DESIGN'][1:], *F['RUNTIME']); objects = F['hashes']({k:obj/k for k in keys})
    need(objects == {k:pins[k] for k in keys} and objects[keys[0]] == ref['candidate_archive_sha256'] and
         h(vt/'bin/verilator_bin') == F['VERILATOR'], 'changed linked objects or translator')
    want = dict(kit_sha256=seal, objects=objects, translator_sha256=F['VERILATOR'], build_log_sha256=h(previous/'build.log'))
    need(json.loads((previous/'build.json').read_bytes()) == want, 'object build drift')
    return obj


def prepare(release, out):
    shared = doc('perf-strict-user-lvt.json')['shared_inputs']
    for p in [ROOT/'tests/rocket_chiptop.cpp', *sorted((ROOT/'tests').glob('chiptop_*.hpp'))]:
        (out/p.name).write_bytes(S['pinned_source'](p.name,p.read_bytes(),shared[p.name]))
    (out/'mega_linux_shell.hpp').write_bytes((ROOT/'tests/mega_linux_shell.hpp').read_bytes())
    (out/'boot.cpp').write_bytes(S['render']((ROOT/'tests/mega_linux_entry.cpp').read_text()).encode())
    frame = S['encode']((release/'fw_payload.bin').read_bytes()[:8]); fault = bytearray(frame); fault[12] ^= 1
    (out/'prefix.frame').write_bytes(frame); (out/'crc.frame').write_bytes(fault)
    nonce = secrets.token_hex(7); (out/'nonce').write_bytes((nonce+'\n').encode('ascii'))
    (out/'commands.txt').write_bytes(('\n'.join(S['commands'](nonce))+'\n').encode('ascii'))


def binding(release, previous, kit, vt, out):
    obj = previous/'obj'; entry = doc(ENTRY); shared = doc('perf-strict-user-lvt.json')['shared_inputs']
    pins = json.loads((previous/'inputs.json').read_bytes())
    paths = {k:out/k for k in ('boot.cpp','mega_linux_shell.hpp','prefix.frame','crc.frame','commands.txt','nonce',
                               'rocket_chiptop.cpp',*('chiptop_'+k+'.hpp' for k in F['PAIR']['HEADERS']))}
    paths.update({k:release/k for k in ('fw_payload.bin','Image',BENCH)})
    paths.update({k:obj/k for k in (*F['DESIGN'][1:],*F['RUNTIME'],'VChipTop.h','VChipTop__verFiles.dat')})
    paths.update({k:ROOT/'docs'/k for k in (ENTRY,PREVIOUS,'perf-strict-user-lvt.json','perf-mega175-linux-identity.json')})
    paths.update({k:HERE/k for k in ('test-mega-recovery-linux.py','test-mega-linux-shell.py','test-mega-recovery-fullcore.py',
                                      'test-copy-load-fullcore.py','check-model-kit.py','verify-mega-impl-inputs.py','test-strict-tl-wait.py',
                                      'mega_linux_shell_review.py','linux_machine_witness.py','uart_frame.py','derive-target-length-crcs.py','review-coremark.py')})
    paths.update({'CANDIDATE.sha256':kit/'CANDIDATE.sha256','mega_linux_entry.cpp':ROOT/'tests/mega_linux_entry.cpp',
                  'replay-inputs.json':previous/'inputs.json', 'verilator_bin':vt/'bin/verilator_bin'})
    got = F['hashes'](paths)
    want = {**entry['inputs'], **OBSERVER, **{k:shared[k] for k in paths if k.startswith('chiptop_')},
            **{k:pins[k] for k in (*F['DESIGN'],*F['RUNTIME'])},'verilator_bin':F['VERILATOR']}
    need(all(got[k] == v for k,v in want.items()), 'changed observer, firmware, model or stimulus')
    nonce = (out/'nonce').read_text().strip(); cmd = '\n'.join(S['commands'](nonce))+'\n'
    need((out/'commands.txt').read_bytes()==cmd.encode('ascii'), 'unexpected command set')
    return got


def check_fault(out):
    ref = doc(ENTRY)['evidence']
    for key in ('crc.events','crc.uart'):
        need(h(out/key) == ref[key], 'reset/ROM CRC rejection differs from stock: '+key)
    return {k:ref[k] for k in ('crc.events','crc.uart')}


def rom_prefix(out):
    fault = check_fault(out); ref = doc(ENTRY)['witness']
    epoch = b'UART5_READY v1\r\nUART5_HANDOFF\r\n'; raw = (out/'linux.uart').read_bytes()
    event = ('ROM_HANDOFF tick=%d wire=24 backing_preloaded=%d edge_intervals=9 ticks_per_bit=1519\n' %
             (ref['valid_rom_handoff_tick'],ref['backing_preloaded_bytes'])).encode('ascii')
    need(raw.startswith(epoch) and (out/'linux.events').read_bytes().startswith(event), 'valid ROM handoff missing or changed')
    return dict(scope='Two recovery ChipTop resets, behavioral external TL RAM; ROM only. No FPGA or Linux benchmark.',
                physical_kit_sha256=R['PAIR'][1], fault_sha256=fault, bad_crc_stop_tick=ref['negative_crc_stop_tick'],
                valid_handoff_tick=ref['valid_rom_handoff_tick'], valid_uart_prefix_bytes=len(epoch),
                valid_uart_prefix_sha256=sha256(epoch).hexdigest(), valid_events_prefix_bytes=len(event),
                valid_events_prefix_sha256=sha256(event).hexdigest())


def main():
    a = argparse.ArgumentParser(description=__doc__); a.add_argument('mode',choices=('run','rom','review'))
    for k in ('physical','kit','previous','release','verilator','out'): a.add_argument(k,type=Path)
    a = a.parse_args(); physical,kit,previous,release,vt = [getattr(a,k).resolve(strict=True) for k in ('physical','kit','previous','release','verilator')]
    obj = qualified(physical,kit,previous,vt); env = F['tool_env'](vt)
    need(not a.out.is_symlink(),'symlink output'); out=a.out.resolve()
    if a.mode=='run':
        F['owned_output'](out,kit,[physical,kit,previous,release,vt,HERE,ROOT/'tests',ROOT/'docs'])
        out.mkdir(mode=0o700); prepare(release,out); base = binding(release,previous,kit,vt,out)
        F['LINK'](out/'boot.cpp',out/'model',obj,vt/'share/verilator/include',env=env)
        base['model'] = h(out/'model'); write(out/'bound.json',base)
        for mode,stem,frame in [('crc','crc','crc.frame'),('valid','linux','prefix.frame')]:
            nonce=(out/'nonce').read_text().strip()
            with (out/(stem+'.uart')).open('xb') as u,(out/(stem+'.events')).open('xb') as e:
                subprocess.run([out/'model', mode, release/'fw_payload.bin', out/frame,out/'commands.txt',nonce],
                               cwd=out,env=env,stdout=u,stderr=e,check=True)
            if mode=='crc': check_fault(out); print('ROM_CRC_CONTROL_EXITED_AND_MATCHED',flush=True)
        qualified(physical,kit,previous,vt)
    current = binding(release,previous,kit,vt,out); current['model']=h(out/'model')
    need(json.loads((out/'bound.json').read_bytes()) == current,'binding drift')
    rom = rom_prefix(out)
    if a.mode=='rom': print(json.dumps(rom,indent=2)); return
    result = S['inspect']((out/'linux.uart').read_bytes(),(out/'linux.events').read_text(),(out/'nonce').read_text().strip())
    result.update(scope='Recovery ChipTop cold Linux boot, behavioral external TL RAM. Four-round CRCs only, not a board score.',
                  rom=rom, model_sha256=current['model'], observer_sha256=current['boot.cpp'],bound_sha256=h(out/'bound.json'))
    if a.mode=='run': write(out/'review.json',result)
    else: need(json.loads((out/'review.json').read_bytes())==result,'full review does not reproduce')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
