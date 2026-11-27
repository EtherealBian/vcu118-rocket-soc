import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
mod = runpy.run_path(str(ROOT/'scripts/derive-target-length-crcs.py'))
cm = mod['CM']
profile = 'g15-gc-lto-ooo-strict'
nonce = '1234567890abcd'
h = 'f' * 64


def section(kind):
    _, seed, lst, matrix, state = cm['CASES'][kind]
    final = {'performance':'0x4983','validation':'0xeb93'}[kind]
    return '\n'.join([f'2K {kind} run parameters for coremark.', 'CoreMark Size : 666', 'Iterations : 24000',
                     'Compiler version : GCC15.1.0', 'Compiler flags : '+cm['PROFILES'][profile][1],
                     'seedcrc : '+seed, '[0]crclist : '+lst, '[0]crcmatrix : '+matrix, '[0]crcstate : '+state,
                     '[0]crcfinal : '+final, mod['SHORT'], 'Errors detected'])


class OracleTests(unittest.TestCase):
    def test_only_short_duration_is_accepted_as_crc_only(self):
        good = section('performance'); check = lambda raw: mod['crc'](raw,'performance',24000)
        self.assertEqual(check(good),'0x4983')
        self.assertEqual(check(good.replace(mod['SHORT']+'\nErrors detected',mod['VALID'])),'0x4983')
        for change in ('ERROR! mismatch','Errors detected','Cannot validate operation','Kernel panic',mod['VALID'],
                       'Parallel PThreads : 2','[1]crcfinal : 0x4983','[0]crcfinal : 0x4983',mod['SHORT']):
            with self.subTest(change=change),self.assertRaises(ValueError):check(good+'\n'+change)
        for a,b in [('Errors detected',''),('24000','12000'),('0xe714','0xe715'),('Size : 666','Size : 667')]:
            with self.assertRaises(ValueError):check(good.replace(a,b))

    def test_guest_requires_same_epoch_build_cpu_and_both_sections(self):
        rows=['# cat /proc/cpuinfo; echo ISA_END_$((40+2))_'+nonce,'processor : 0','hart : 0','isa : rv64imafdc_zicsr',
              'ISA_END_42_'+nonce,'CM_LIVE_42_'+nonce,'# '+cm['command'](nonce,24000,profile),h+'  '+cm['binary'](profile)]
        for kind in cm['CASES']:rows.extend([f'CM_{kind}_42_{nonce}',section(kind),f'CM_{kind}_RC_0_{nonce}'])
        rows.append('CM_DONE_42_'+nonce);raw='\n'.join(rows)
        def check(s):return mod['guest_crcs'](s.encode(),nonce,h,profile,24000)
        self.assertEqual(check(raw),{'performance':'0x4983','validation':'0xeb93'})
        for a,b in [('hart : 0','hart : 1'),('rv64imafdc_zicsr','rv64imafdc_zicsr_zba'),('processor : 0','processor : 0\nprocessor : 1'),
                    ('GCC15.1.0','GCC14.1.0'),('Compiler flags : -O3','Compiler flags : -O0'),('CM_validation_RC_0','CM_validation_RC_1'),
                    ('CM_DONE_42','Kernel panic\nCM_DONE_42'),(' 0x66 24000',' 0x66 12000')]:
            with self.subTest(a=a),self.assertRaises(ValueError):check(raw.replace(a,b))
        with self.assertRaises(ValueError):check(raw+'\n'+rows[-1])
