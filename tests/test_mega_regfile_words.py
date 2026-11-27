from pathlib import Path
import json
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROOF = runpy.run_path(str(ROOT / 'scripts/prove-mega-regfile-words.py'))
SHAPES = [(64, 12, 6), (65, 6, 4)]


def enclosing(bits, readers, writers):
    pins = [f'.R{i}_clk(clock)' for i in range(readers)]
    for w in range(writers):
        parent = f'io_write_ports_{writers - 1 - w}'
        pins.extend([f'.W{w}_clk(clock)', f'.W{w}_addr({parent}_bits_addr)',
                     f'.W{w}_en({parent}_valid)', f'.W{w}_data({parent}_bits_data)'])
    return f'regfile_128x{bits} regfile_ext (' + ',\n'.join(pins) + ');'


class WordProofTests(unittest.TestCase):
    def test_partition_by_highest_flat_hit(self):
        for bits, readers, writers in SHAPES:
            for role in ('alt', 'ref'):
                declarations, laws = PROOF['obligations'](role, bits, readers, writers)
                self.assertIn('(declare-const q (_ BitVec 7))', declarations)
                edge = ['(|dut_h| a)', '(|dut_h| b)', '(|dut_t| a b)']
                self.assertEqual(laws['hold'][0], edge + [f'(not hit{w})' for w in range(writers)])
                memories = (['storage.owner'] + [f'storage.writer[{w}].bank' for w in range(writers)]
                            if role == 'alt' else ['Memory'])
                for memory in memories:
                    for state in ('a', 'b'):
                        self.assertIn(f'(select (|dut_m {memory}| {state}) q)', laws['hold'][1])
                for w in range(writers):
                    pre, prop = laws[f'write{w}']
                    self.assertEqual(pre, edge + [f'hit{w}'] + [f'(not hit{i})' for i in range(w+1, writers)])
                    self.assertIn(f'(|dut_n W{w}_data| a)', prop)
                    self.assertIn(f'(= q (|dut_n W{w}_addr| a))', declarations)
                    self.assertIn(f'(and (|dut_n W{w}_en| a)', declarations)

    def test_all_read_lanes_and_banks_are_checked_without_an_edge(self):
        for bits, readers, writers in SHAPES:
            for role in ('alt', 'ref'):
                _, laws = PROOF['obligations'](role, bits, readers, writers)
                count = readers * (writers if role == 'alt' else 1)
                self.assertEqual(len(laws), 1 + writers + count)
                for r in range(readers):
                    for w in range(writers if role == 'alt' else 1):
                        name = f'read{r}' + (f'_bank{w}' if role == 'alt' else '')
                        pre, prop = laws[name]
                        self.assertEqual(pre[:3], ['(|dut_h| a)', f'(|dut_n R{r}_en| a)', f'(= q (|dut_n R{r}_addr| a))'])
                        self.assertEqual(len(pre), 4 if role == 'alt' else 3)
                        if role == 'alt':
                            self.assertIn(f'(_ bv{w} {(writers-1).bit_length()})', pre[3])
                        memory = f'storage.writer[{w}].bank' if role == 'alt' else 'Memory'
                        self.assertEqual(prop, f'(= (|dut_n R{r}_data| a) (select (|dut_m {memory}| a) q))')

    def test_foreign_interfaces_are_rejected(self):
        for profile in [('any', 64, 12, 6), ('alt', 63, 12, 6), ('ref', 65, 12, 6), ('alt', 64, 6, 4)]:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                PROOF['obligations'](*profile)

    def test_answers_must_match_the_complete_nonvacuous_protocol(self):
        check = PROOF['check_answers']
        names = ['hold', 'write0']
        for negative, answer, wrong in [(False, 'unsat', 'sat'), (True, 'sat', 'unsat')]:
            text = f'hold\nsat\n{answer}\nwrite0\nsat\n{answer}\n'
            check(text, names, negative)
            for bad in [text.replace('hold\nsat', 'hold\nunsat', 1), text.replace('write0', 'hold'),
                        text.swapcase(), text[:text.index('write0')], text+'sat\n',
                        text.replace('hold\nsat\n'+answer, 'hold\nsat\n'+wrong), text+'unknown\n',
                        text.replace('write0\nsat', 'write0\nunknown')]:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    check(bad, names, negative)

    def test_parent_mapping_rejects_crossed_fields_order_or_clocks(self):
        for shape in SHAPES:
            bits, readers, writers = shape
            check = lambda x: PROOF['parent_lanes'](x, *shape)
            text = enclosing(*shape)
            self.assertEqual(check(text), list(reversed(range(writers))))
            for a, b in [('_0_bits_addr', '_1_bits_addr'), ('_0_valid', '_1_valid'),
                         ('_0_bits_data', '_1_bits_data'), ('.R0_clk(clock)', ''),
                         ('.W0_clk(clock)', '.W0_clk(other)'), ('io_write_ports_0_', 'io_write_ports_1_')]:
                with self.subTest(a=a), self.assertRaises(ValueError):
                    check(text.replace(a, b))
            with self.assertRaises(ValueError):
                check(text + text)

    def test_published_report_matches_exact_dut_pair_and_complete_inventory(self):
        report = json.loads((ROOT / 'docs/perf-mega175-regfile-words.json').read_bytes())
        pair = json.loads((ROOT / 'docs/perf-mega175-regfile-input.json').read_bytes())
        self.assertEqual((report['stock_seal'], report['candidate_seal']),
                         (pair['stock_board_seal'], pair['candidate_board_input_seal']))
        expected = set()
        for bits, readers, writers in SHAPES:
            self.assertEqual(report['flat_writer_to_parent_port'][str(bits)], list(reversed(range(writers))))
            controls = {'wrong_priority': f'write{writers-1}', 'wrong_bank_data': f'write{writers-1}',
                        'wrong_read_lane': 'read0_bank0', 'stray_write': 'hold'}
            for kind in ['ref', 'alt', *controls]:
                name = f'{bits}-{kind}'
                expected.add(name)
                row = report['cases'][name]
                bad = kind in controls
                laws = [controls[kind]] if bad else list(PROOF['obligations'](kind, bits, readers, writers)[1])
                self.assertEqual(row['laws'], laws)
                self.assertEqual((row['antecedents_satisfiable'], row['proved'], row['counterexamples']),
                                 (len(laws), 0 if bad else len(laws), 1 if bad else 0))
                for k in ('smt2_sha256', 'answer_sha256'):
                    self.assertRegex(row[k], r'^[0-9a-f]{64}$')
        self.assertEqual(set(report['cases']), expected)
