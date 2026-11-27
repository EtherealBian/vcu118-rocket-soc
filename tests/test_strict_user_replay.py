import hashlib
from pathlib import Path
import runpy
import struct
import unittest

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-user-replay.py'))
PC = [0x106b0, 0x13b0c, 0x13b0c] + [0x10af0, 0x13b0c, 0x13b0c]*3

def buf(seq):
    return b''.join(struct.pack('<I', x) for x in seq)

TRACE = buf(PC)
REF = dict(dynamic_instructions=12, ordered_pc_sha256=hashlib.sha256(TRACE).hexdigest(), by_round=[3]*4)
EVENTS = ('MRET tick=100 epc=106b0 ret=1 satp=8 uart_bytes=21\n'
          'EXIT start=100 stop=120 cycles=20 u_arch_valid=16 mepc=147b4 cause=8 tval=0 lanes=4,16,0,0,0,\n'
          'WINDOW hot=12 pre=800000ec, post=10f3a,147ac,147b0, fences=102,106,110,114,118,\n')

class UserReplayTests(unittest.TestCase):
    def check(self, events=EVENTS, uart=M['EPOCH'], trace=TRACE, ref=REF):
        return M['inspect'](events, uart, trace, ref)

    def test_exact_interval_is_not_the_privilege_interval(self):
        out = self.check(); self.assertEqual(out['user_window_cycles'], 16)
        self.assertEqual(out['privilege_interval_cycles'], 20)
        self.assertEqual(out['by_round_cycles'], [4]*4)

    def test_different_order_same_histogram(self):
        bad = PC[:]; bad[2],bad[3] = bad[3],bad[2]
        for trace in (buf(bad), TRACE[4:], TRACE+b'\0', buf(PC[::-1])):
            with self.subTest(), self.assertRaises(ValueError): self.check(trace=trace)

    def test_bad_snapshot_result_even_if_trace_matches(self):
        for uart in (M['EPOCH'][:-1], M['EPOCH'][:-1]+b'!', M['EPOCH']+b'K'):
            with self.subTest(), self.assertRaises(ValueError): self.check(uart=uart)

    def test_csr_and_arch_valid_boundaries(self):
        for old,new in [('epc=106b0','epc=106b4'), ('satp=8','satp=9'), ('cause=8','cause=12'),
                        ('800000ec,',''), ('147b0,','147b4,'), ('u_arch_valid=16','u_arch_valid=15'),
                        ('16,0,0,0,','15,1,0,0,'), ('106,110','111,110'), ('118,','121,')]:
            with self.subTest(old=old), self.assertRaises(ValueError): self.check(events=EVENTS.replace(old,new))

    def test_round_and_list_boundaries_independent_of_digest(self):
        for pos,value in [(0,0x106b2), (3,0x10af2), (7,0x13b0e), (11,0x10f3a)]:
            bad=PC[:]; bad[pos]=value; trace=buf(bad)
            with self.subTest(), self.assertRaises(ValueError):
                self.check(trace=trace,ref=dict(REF,ordered_pc_sha256=hashlib.sha256(trace).hexdigest()))

class SnapshotInputTests(unittest.TestCase):
    def make(self, wrong=None):
        import json
        import sys
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        scripts=Path(__file__).resolve().parents[1]/'scripts'
        with patch.object(sys,'path',[str(scripts)]+sys.path):
            build=runpy.run_path(str(scripts/'build-strict-user-replay.py'))['build']
        with TemporaryDirectory() as tmp:
            d=Path(tmp); regs=[0]*32; regs[2]=0x40000000; regs[9]=0x44000
            areas=[['text',0x10158,44712],['rw',0x20f50,3120],['stack',regs[2]-1536,1728],['heap',regs[9],2000]]
            for tag,pc in [('in',0x106b0),('out',0x10f3a)]:
                state=dict(priv=0,satp=8<<60,pc=pc,regs=regs,areas=areas)
                if wrong and tag=='out': state.update(wrong)
                (d/(tag+'.json')).write_text(json.dumps(state))
                for name,_,size in areas: (d/(tag+'-'+name)).write_bytes(bytes(size))
            if not wrong: (d/'out-text').write_bytes(b'X'+bytes(44711))
            # All negatives must fail before trying to run any cross tool.
            with patch('subprocess.run',side_effect=AssertionError('compiler should be unreachable')):
                build(d, bytes(67008), 'absent-')

    def test_requires_actual_sv39_user_boundary(self):
        for wrong in [dict(priv=1), dict(satp=10<<60), dict(pc=0x10f3e)]:
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError,'Sv39 user window'): self.make(wrong)

    def test_requires_full_register_state_and_spans(self):
        for wrong in [dict(regs=[0]*31), dict(regs=[1]*32), dict(areas=[])]:
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError,'GPRs|spans'): self.make(wrong)

    def test_rejects_patched_guest_text(self):
        with self.assertRaisesRegex(ValueError,'changed text'): self.make()


class ReplayPairTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        self.t = TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.pair = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/review-strict-replay-pair.py'))
        self.base = Path(self.t.name).resolve()
        self.guest = self.base / 'guest'
        self.pins = {'models': {}}
        self.oracle = {'results': {s: REF for s in self.pair['SEEDS']}}
        self.roles = {}
        for s in self.pair['SEEDS']:
            p = self.guest / s / 'replay'; p.mkdir(parents=True)
            (p / 'mem.bin').write_bytes(s.encode()); (p / 'prefix.frame').write_bytes(b'frame')
        for role in ('stock', 'lvt'):
            kit, obj, run = [self.base / role / n for n in ('kit', 'obj', 'run')]
            for p in (kit, obj, run): p.mkdir(parents=True)
            self.roles[role] = (kit, obj, run)
            paths = []; pins = {}
            for i,n in enumerate(self.pair['DESIGN']):
                p = (kit if i == 0 else obj) / n; p.write_bytes((role+n).encode())
                paths.append(p); pins[n] = hashlib.sha256(p.read_bytes()).hexdigest()
            self.pins['models'][role] = pins
            for n in self.pair['RUNTIME']:
                p = obj / n; p.write_bytes(n.encode()); paths.append(p)
            (run / 'model').write_bytes(role.encode()); paths.append(run / 'model')
            paths.extend(self.pair['ROOT'] / 'tests' / n for n in self.pair['HARNESS'])
            for s in self.pair['SEEDS']:
                paths.extend(self.guest / s / 'replay' / n for n in ('mem.bin', 'prefix.frame'))
                for n,b in [('pc',TRACE), ('uart',M['EPOCH']), ('events',EVENTS.encode())]:
                    (run / f'{s}.{n}').write_bytes(b)
            (run / 'inputs.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p)+'\n' for p in paths))

    def read(self, role, label=None):
        return self.pair['review_run'](label or role, *self.roles[role], self.guest, self.pins, self.oracle)

    def test_scoped_inputs_and_separate_linked_models(self):
        a,b = self.read('stock'), self.read('lvt')
        r = self.pair['compare'](a,b,'elf')
        self.assertEqual(r['matched_windows']['validation']['by_round_cycles'], [4]*4)
        self.assertEqual(r['matched_windows']['validation']['privilege_interval_cycles_by_retired_width_0_to_4'],
                         [4,16,0,0,0])
        self.assertNotEqual(r['shared_inputs']['performance/mem.bin'], r['shared_inputs']['validation/mem.bin'])
        b['hashes']['model'] = a['hashes']['model']
        with self.assertRaisesRegex(ValueError,'separate designs'): self.pair['compare'](a,b,'elf')

    def test_same_run_with_foreign_role_and_stale_executable(self):
        with self.assertRaisesRegex(ValueError,'match its design'): self.read('lvt','stock')
        (self.roles['lvt'][2] / 'model').write_bytes(b'stock')
        with self.assertRaisesRegex(ValueError,'changed replay input'): self.read('lvt')

    def test_swapped_seed_ram_and_duplicated_manifest_item(self):
        p,q = (self.guest / s / 'replay' / 'mem.bin' for s in self.pair['SEEDS'])
        old = p.read_bytes(); p.write_bytes(q.read_bytes())
        with self.assertRaisesRegex(ValueError,'changed replay input'): self.read('lvt')
        p.write_bytes(old)
        f = self.roles['lvt'][2] / 'inputs.sha256'; data = f.read_text()
        f.write_text(data+data.splitlines()[0]+'\n')
        with self.assertRaisesRegex(ValueError,'duplicate'): self.read('lvt')

    def test_one_cycle_shift_is_not_an_equal_pair(self):
        (self.roles['lvt'][2] / 'performance.events').write_text(EVENTS.replace('102,106,','102,107,'))
        with self.assertRaisesRegex(ValueError,'per-round cycles'):
            self.pair['compare'](self.read('stock'), self.read('lvt'), 'elf')
