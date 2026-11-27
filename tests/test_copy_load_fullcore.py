from hashlib import sha256
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE.parent / 'scripts/test-copy-load-fullcore.py'))
F = runpy.run_path(str(HERE / 'test_strict_user_replay.py'))


class FullcoreReplayTests(unittest.TestCase):
    def setUp(self):
        self.raw = dict(events=F['EVENTS'].encode(), uart=F['M']['EPOCH'], pc=F['TRACE'])
        old = M['PAIR']['REPLAY']['inspect'](F['EVENTS'], self.raw['uart'], self.raw['pc'], F['REF'], include_widths=True)
        self.base = dict(results={'performance': old}, evidence={'performance': {k: sha256(v).hexdigest() for k, v in self.raw.items()}})

    def compare(self, **changes):
        return M['compare']('performance', {**self.raw, **changes}, self.base, F['REF'])

    def test_signed_per_round_and_total_not_only_average(self):
        for fences, expected in [('102,106,110,114,118', [0, 0, 0, 0]), ('102,105,110,113,117', [-1, 1, -1, 0]),
                                 ('102,107,111,115,119', [1, 0, 0, 0]), ('102,107,110,114,118', [1, -1, 0, 0])]:
            with self.subTest(fences=fences):
                r = self.compare(events=F['EVENTS'].replace('102,106,110,114,118', fences).encode())
                self.assertEqual(r['candidate_minus_stock_cycles'], expected)
                self.assertEqual(r['total_delta_cycles'], sum(expected))

    def test_bad_guest_state_order_or_timing_cannot_be_a_speedup(self):
        p = list(F['PC']); p[2], p[3] = p[3], p[2]
        for change in (dict(uart=self.raw['uart'][:-1] + b'!'), dict(pc=F['buf'](p)), dict(pc=self.raw['pc'][:-4]),
                       dict(events=F['EVENTS'].replace('110,114', '110,110').encode())):
            with self.subTest(change=tuple(change)), self.assertRaises(ValueError):
                self.compare(**change)

    def test_good_oracle_still_must_match_archived_execution(self):
        self.base['evidence']['performance']['pc'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'PC or guest-state'):
            self.compare()

    def test_build_and_guest_bindings(self):
        seal, lib, header = M['DESIGN']
        old = {k: 'old/' + k for k in (*M['DESIGN'], 'model', *M['RUNTIME'], 'rt.cpp', 'performance/mem.bin', 'validation/mem.bin')}
        now = {**old, **{k: 'new/' + k for k in (seal, lib, 'model')}}
        base = {'hashes': old}; check = M['check_bindings']
        check(now, base); check({**now, header: 'changed-layout'}, base)
        for bad in [{**now, k: old[k]} for k in (seal, lib, 'model')] + [
                {**now, k: 'swapped'} for k in ('rt.cpp', *M['RUNTIME'], 'performance/mem.bin', 'validation/mem.bin')
        ] + [{k: v for k, v in now.items() if k != header}]:
            with self.subTest(), self.assertRaisesRegex(ValueError, 'distinct candidate'):
                check(bad, base)

    def test_translation_flags_are_not_only_a_source_file_list(self):
        with TemporaryDirectory() as tmp, patch.dict(M['check_translation'].__globals__, CHECK=lambda *args: None):
            obj = Path(tmp); kit = obj / 'kit'; record = obj / 'VChipTop__verFiles.dat'
            good = 'C "' + ' '.join(M['translation_args'](kit, obj)) + '"\n'; record.write_text(good)
            M['check_translation'](kit, obj)
            for bad in (good + good, good.replace('-O2', '-O3'), good.replace('ChipTop ', 'WrongTop ')):
                record.write_text(bad)
                with self.assertRaisesRegex(ValueError, 'translation flags'):
                    M['check_translation'](kit, obj)

    def test_output_cannot_alias_private_evidence_or_escape_parent(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve(); kit = parent / 'kit'; kit.mkdir()
            sealed = parent / 'runs' / 'stock'; sealed.mkdir(parents=True)
            def check(p): M['owned_output'](p, kit, [kit, sealed])
            check(parent / 'fresh')
            for p in (parent, kit, sealed, kit / 'new', sealed / 'new', sealed.parent, parent.parent / 'elsewhere'):
                with self.subTest(p=p), self.assertRaisesRegex(ValueError, 'fresh disjoint'):
                    check(p)

    def test_ambient_make_compiler_and_preload_do_not_replace_candidate(self):
        with patch.dict(os.environ, HOME='/home/test', CXX='foreign', MAKEFLAGS='-j64', LD_PRELOAD='foreign'):
            env = M['tool_env'](Path('/tools'))
            with patch('subprocess.run') as sub:
                M['LINK'](Path('x.cpp'), Path('exe'), Path('obj'), Path('include'), env=env)
            self.assertEqual(sub.call_args.args[0][0], 'g++')
            self.assertEqual(sub.call_args.kwargs['env'], env)
            self.assertFalse({'CXX', 'MAKEFLAGS', 'LD_PRELOAD'} & env.keys())
