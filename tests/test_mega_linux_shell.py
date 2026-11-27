"""Synthetic parser and host-pin tests, not RTL or board benchmark evidence."""
from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import mega_linux_shell_review as m
N='0123456789abcd'; CMD=m.commands(N)


def fixture():
    ref=json.loads((ROOT/'docs/perf-mega175-linux-entry.json').read_bytes())
    prefix=b'fixture entry\r\n'; original='fixture events\n'; ref['evidence']={'boot.uart':sha256(prefix).hexdigest(),'boot.events':sha256(original.encode()).hexdigest()}
    elf=ref['embedded_benchmark']['elf_sha256']; lines=['Linux version 6.6.65 fixture','[    0.000000] efi: UEFI not found.',
            'VCU118_INITRAMFS_READY','SOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=0',
            'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d',
            'BusyBox v1.36.1 (fixture) built-in shell (ash)','# '+CMD[0],'CM_LIVE_42_'+N,'# '+CMD[1],f'CM_BOOT_{N}_42_{N}',
            '0','processor : 0','hart : 0','uarch : ucb-bar,boom0']
    _,dig=m.machine.expected(m.machine.MEGA_SEAL);lines.extend(h+'  '+m.machine.SYSFS+p for h,p in zip(dig,m.machine.PROPERTIES))
    lines+=['CM_MACHINE_END_42_'+N,'# '+CMD[2],elf+'  '+m.CM['binary'](m.PROFILE)]
    for kind,(_,seed,lst,mat,state) in m.CM['CASES'].items():
        lines += [f'CM_{kind}_42_{N}',f'2K {kind} run parameters for coremark.',
                  'CoreMark Size : 666','Iterations : 4','Compiler version : GCC15.1.0','Compiler flags : '+m.CM['PROFILES'][m.PROFILE][1],
                  'seedcrc : '+seed,'[0]crclist : '+lst,'[0]crcmatrix : '+mat,'[0]crcstate : '+state,'[0]crcfinal : '+m.CRC4[kind],
                  m.CRC['SHORT'],'Errors detected',f'CM_{kind}_RC_0_{N}']
    lines+=['CM_DONE_42_'+N]
    t=ref['witness']['observation_end_tick']; stamps=[]
    for j,c in enumerate(CMD,1):
        t+=10000;stamps.append((t,f'SHELL_TX tick={t} step={j} bytes={len(c)+1}'))
        t+=24*1519*(len(c)+1);stamps.append((t,f'SHELL_REPLY tick={t} step={j}'))
    stamps.append((t,f'SHELL_WIRE_DONE tick={t}'))
    for x in range(45000000,t,5000000):stamps.append((x,f'PROGRESS cycles={x} reads=2500 writes=120'))
    events=original+f'ENTRY_PREFIX bytes={len(prefix)}\n'+''.join(s+'\n' for _,s in sorted(stamps))
    return prefix+('\r\n'.join(lines)+'\r\n').encode(), events, ref


class LinuxShellTests(unittest.TestCase):
    def setUp(self):
        self.raw,self.events,ref=fixture();read=Path.read_bytes
        context=patch.object(Path,'read_bytes',lambda p: json.dumps(ref).encode() if p.name=='perf-mega175-linux-entry.json' else read(p))
        context.start();self.addCleanup(context.stop)

    def test_only_exact_historical_bytes_enter_compiler(self):
        pin=runpy.run_path(str(ROOT/'scripts/test-mega-linux-shell.py'))['pinned_source']
        shared=json.loads((ROOT/'docs/perf-strict-user-lvt.json').read_bytes())['shared_inputs']
        for k in ('chiptop_address.hpp','chiptop_sd.hpp'):
            data=(ROOT/'tests'/k).read_bytes().replace(b'\r\n',b'\n')
            self.assertEqual(sha256(pin(k,data,shared[k])).hexdigest(),shared[k])
            with self.assertRaises(ValueError):pin(k,b' '+data,shared[k])
            with self.assertRaises(ValueError):pin('different.hpp',data,shared[k])

    def test_short_crc_not_a_score(self):
        result=m.inspect(self.raw,self.events,N);self.assertEqual(result['final_crcs'],m.CRC4)
        self.assertNotIn('iterations_per_s',result)

    def test_linux_may_probe_empty_spi_slot_only_after_entry(self):
        marker='POST_ENTRY_SPI_SELECT tick=40822500\n';pos=self.events.index('SHELL_TX')
        def add(text):return self.events[:pos]+text+self.events[pos:]
        self.assertEqual(m.inspect(self.raw,add(marker),N)['first_post_entry_spi_select_tick'],40822500)
        for bad in (marker*2,marker.replace('40822500','40822448')):
            with self.assertRaises(ValueError):m.inspect(self.raw,add(bad),N)
        script=runpy.run_path(str(ROOT/'scripts/test-mega-linux-shell.py'))
        source=script['render']((ROOT/'tests/mega_linux_entry.cpp').read_text())
        self.assertIn('if(!entry)need(t.spi_0_cs_0,',source); self.assertIn('t.spi_0_dq_1_i=1;',source)

    def test_reject_wrong_guest_workload_or_echo_only(self):
        for a,b in [(b'fixture entry',b'changed entry'),(b'CM_LIVE_42_',b'CM_LIVE_$((40+2))_'),(b'ucb-bar,boom0',b'sifive,rocket0'),
                    (b'SOC_CHECK_PASS',b'Not found'),(b'  /sys/firmware/',b'  /sys/other/'),(b'0x9f95',b'0x19d9'),(b'0x18f2',b'0xe9f5'),
                    (b'0x3415 0x3415 0x66 4',b'0x3415 0x3415 0x66 2'),(b'Errors detected',b'ERROR! extra\r\nErrors detected'),
                    (b'CM_validation_RC_0_',b'CM_validation_RC_1_'),(b'CM_DONE_42_',b'CM_DONE_$((40+2))_'),(b'processor : 0',b'sh: probe: not found\r\nprocessor : 0')]:
            with self.subTest(a=a),self.assertRaises(ValueError):m.inspect(self.raw.replace(a,b),self.events,N)

    def test_reject_truncated_or_impossible_model_trace(self):
        for a,b in [('fixture events','changed events'),('ENTRY_PREFIX bytes=15','ENTRY_PREFIX bytes=2'),('cycles=45000000','cycles=44999999'),
                    ('writes=120','writes=12'),('step=2','step=1'),('SHELL_WIRE_DONE','NO_WIRE_DONE')]:
            self.assertIn(a,self.events)
            with self.subTest(a=a),self.assertRaises(ValueError):m.inspect(self.raw,self.events.replace(a,b),N)
        with self.assertRaises(ValueError):m.inspect(self.raw,'',N)

    @unittest.skipUnless(shutil.which('c++'),'requires host C++ compiler')
    def test_real_tx_framing_and_reply_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'cmd').write_text('\n'.join(CMD)+'\n');exe=d/'check'
            subprocess.run(['c++','-std=c++17','-O2',ROOT/'tests/mega_linux_shell_pins.cpp','-o',exe],check=True)
            subprocess.run([exe,d/'cmd',N],check=True,capture_output=True)
