#!/usr/bin/env python3
"""Run Linux on the original four-wide functional model, never on hardware."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import secrets
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from uart_frame import encode
from mega_linux_shell_review import commands, inspect

LIB = runpy.run_path(str(HERE/'test-strict-tl-wait.py'))
LIMIT = 2400000000


def render(source):
    # Reuse the sealed kernel entry witness verbatim up to its original stop.
    hooks = [('#define C(field)', '#include "mega_linux_shell.hpp"\n#define C(field)'),
             ('argc==4', 'argc==6'), ('unsigned retired=0;', 'uint64_t retired=0; bool entry=false, sd_seen=false; LinuxShell shell(argv[4],argv[5]);'),
             ('80000000ULL', str(LIMIT)+'ULL'), ('    ram.drive(t);', '    if(shell.sent)t.uart_0_rxd=shell.pin(i,p);\n    ram.drive(t);'),
             ('need(t.spi_0_cs_0,"unexpected SD select");',
              'if(!entry)need(t.spi_0_cs_0,"unexpected boot SD select"); '
              'else if(!t.spi_0_cs_0&&!sd_seen){sd_seen=true;std::cerr<<"POST_ENTRY_SPI_SELECT tick="<<i<<"\\n";}'),
             ('if(mret && prv==1 && kget)', 'if(!entry && mret && prv==1 && kget)'),
             ('uart.size()<65536', 'uart.size()<262144'),
             ('      if(uart==ready)', '      if(shell.receive(uart,i,p,entry)){t.final();std::cerr<<"SHELL_WIRE_DONE tick="<<i<<"\\n";return 0;}\n      if(uart==ready)'),
             ('if(mret&&kget&&retired>=256){t.final();', 'if(!entry&&mret&&kget&&retired>=256){entry=true;'),
             ('<<ram.writes<<"\\n";return 0;', '<<ram.writes<<"\\n";std::cerr<<"ENTRY_PREFIX bytes="<<uart.size()<<"\\n";')]
    for old, new in hooks:
        if source.count(old) != 1:
            raise ValueError('missing or ambiguous entry hook: '+old)
        source = source.replace(old, new)
    return source


def pinned_source(name, data, digest):
    # Git normalizes the final CRLF on two historic include files. Materialize
    # the original bytes only in the private build, never relax the SHA check.
    if (name in ('chiptop_address.hpp','chiptop_sd.hpp') and data.endswith(b'\n') and
            sha256(data).hexdigest()!=digest):
        data=data[:-1]+b'\r\n'
    if sha256(data).hexdigest()!=digest:
        raise ValueError('changed sealed source: '+name)
    return data


def run(kit, obj, release, out, include):
    runpy.run_path(str(HERE/'check-model-kit.py'))['check'](obj,kit)
    subprocess.run(['sha256sum', '--quiet', '-c', 'CANDIDATE.sha256'], cwd=kit, check=True)
    ref = json.loads((ROOT/'docs/perf-mega175-linux-entry.json').read_bytes())
    out.mkdir(mode=0o700)
    shared=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())['shared_inputs']
    paths={'CANDIDATE.sha256':kit/'CANDIDATE.sha256'}
    paths.update({k:obj/k for k in ('VChipTop__ALL.a','VChipTop___024root.h','verilated.o','verilated_threads.o')})
    for p in [ROOT/'tests/rocket_chiptop.cpp', *sorted((ROOT/'tests').glob('chiptop_*.hpp'))]:
        copy=out/p.name;copy.write_bytes(pinned_source(p.name,p.read_bytes(),shared[p.name])); paths[p.name]=copy
    src = ROOT/'tests/mega_linux_entry.cpp'
    fw = release/'fw_payload.bin'
    frame = out/'prefix.frame'
    frame.write_bytes(encode(fw.read_bytes()[:8]))
    paths.update({p.name:p for p in (src, fw, release/'Image', release/'coremark-g15-gc-lto-ooo-strict.elf', frame)})
    def sums():
        return {k:sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    base = sums()
    for k, digest in {**ref['inputs'], **ref['models']['stock'], **{k:shared[k] for k in ('verilated.o','verilated_threads.o')}}.items():
        if k not in ('crc.frame', 'model') and base.get(k) != digest:
            raise ValueError('not the pin-qualified stock kernel entry input: '+k)
    nonce = secrets.token_hex(7)
    cmd = out/'commands.txt'
    cmd.write_bytes(('\n'.join(commands(nonce))+'\n').encode('ascii'))
    (out/'nonce').write_text(nonce+'\n')
    cpp = out/'boot.cpp'; cpp.write_bytes(render(src.read_text()).encode())
    model = out/'model'
    paths.update({p.name:p for p in (ROOT/'tests/mega_linux_shell.hpp', cpp, cmd, out/'nonce', Path(__file__), HERE/'mega_linux_shell_review.py',
                                      HERE/'check-model-kit.py', HERE/'test-strict-tl-wait.py', HERE/'uart_frame.py', ROOT/'docs/perf-strict-user-lvt.json',
                                      HERE/'derive-target-length-crcs.py', HERE/'review-coremark.py', HERE/'linux_machine_witness.py',
                                      ROOT/'docs/perf-mega175-linux-entry.json', ROOT/'docs/perf-mega175-linux-identity.json')})
    fixed = sums()
    if any(fixed[k]!=v for k,v in base.items()):
        raise ValueError('inputs changed during setup')
    LIB['link'](cpp, model, obj, include)
    fixed['model'] = sha256(model.read_bytes()).hexdigest(); paths['model'] = model
    (out/'inputs.json').write_text(json.dumps(fixed,indent=2)+'\n')
    uart, events = out/'linux.uart', out/'linux.events'
    with uart.open('xb') as u, events.open('xb') as e:
        subprocess.run([model, 'valid', fw, frame, cmd, nonce], stdout=u, stderr=e, check=True)
    if sums() != fixed:
        raise ValueError('inputs changed during execution')
    result = inspect(uart.read_bytes(), events.read_text(), nonce)
    (out/'review.json').write_text(json.dumps(result,indent=2)+'\n')
    print('FOUR_WIDE_MODEL_USERSPACE_CRC_ONLY_NOT_A_BOARD_SCORE')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('kit','obj','release','out','include'):
        ap.add_argument(name,type=Path)
    run(**{k:v.resolve() for k,v in vars(ap.parse_args()).items()})
