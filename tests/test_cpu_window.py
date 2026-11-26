import importlib.util
import copy
from pathlib import Path
import sys
import unittest

S = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0,str(S))
from cpu_window_report import START, END, GOLD, windows
spec=importlib.util.spec_from_file_location('cpu_model_report',S/'review-cpu-window.py'); model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
spec=importlib.util.spec_from_file_location('board_capture',S/'verify-soc-capture.py'); board=importlib.util.module_from_spec(spec);spec.loader.exec_module(board)


def guest():
    rows=[START]
    for j in range(3):
        for k,(a,b,c,d) in GOLD.items():
            rows.append(f'CPUWIN seed={k} sample={j} iterations=4 cycles={200+j} retired=301 list={a} matrix={b} state={c} final={d}')
    return '\n'.join([*rows,END,''])


class WindowTests(unittest.TestCase):
    def test_order_crcs_and_counter_bounds(self):
        s=guest(); r=windows(s.splitlines())['performance_seed'];self.assertEqual(r['median_cycles_per_iteration'],50.25);self.assertEqual(r['median_retired_per_iteration'],75.25);self.assertGreater(r['median_ipc'],1)
        for bad in (s.replace('seed=13333','seed=0',1),s.replace('final=40853','final=6617',1),s.replace('cycles=200','cycles=0',1),s.replace('iterations=4','iterations=400',1),s+'trailer\n',s.replace('sample=2','sample=0',1)):
            with self.subTest(bad=bad),self.assertRaises(ValueError):windows(bad.splitlines())

    def test_model_vs_physical_evidence(self):
        s=guest(); suffix='\nCPU_WINDOW_MODEL_PASS mode=debug-cpu-window cycles=3000 sectors_started=0 tl_read_transactions=2 tl_write_transactions=1 (behavioral RAM/card, no physical DDR)\n'
        self.assertIn('validation_seed',model.decode('PARTIAL_ROM_PRINT'+s+suffix))
        self.assertEqual(model.decode(s+suffix.replace('write_transactions=1','write_transactions=0'))['backing_writes'],0)
        for bad in (s,s+suffix.replace('read_transactions=2','read_transactions=0'),s+suffix.replace('cycles=3000','cycles=101'), s+suffix.replace('sectors_started=0','sectors_started=1'),s+suffix+'junk'):
            with self.assertRaises(ValueError):model.decode(bad)
        wire=('UART5_READY v1\nUART5_HANDOFF\n'+s).replace('\n','\r\n').encode();self.assertIn('cpu_window_diagnostic',board.check_uart(wire,'cpu-window',None))
        for bad in (wire+b'junk',wire.replace(b'final=40853',b'final=1'),wire.replace(b'UART5_HANDOFF',b'NO_HANDOFF')):
            with self.assertRaises(ValueError):board.check_uart(bad,'cpu-window',None)

    def test_comparison_requires_same_work_different_hardware(self):
        spec=importlib.util.spec_from_file_location('compare_window',S/'compare-cpu-window.py'); compare=importlib.util.module_from_spec(spec);spec.loader.exec_module(compare)
        a=windows(guest().splitlines()); a['inputs']={k:k for k in ('window.elf','window.bin','rocket_chiptop.cpp','sim','CANDIDATE.sha256')}; b=copy.deepcopy(a)
        with self.assertRaises(ValueError):compare.compare(a,b)
        b['inputs'].update({'sim':'two','CANDIDATE.sha256':'another'});self.assertEqual(compare.compare(a,b)['comparison']['validation_seed']['reference_to_candidate_cycle_ratio'],1)
        for key in ('window.bin','window.elf','rocket_chiptop.cpp'):
            other=copy.deepcopy(b);other['inputs'][key]+='x'
            with self.assertRaises(ValueError):compare.compare(a,other)
        b['performance_seed']['samples'][1]['retired']+=1
        with self.assertRaises(ValueError):compare.compare(a,b)
