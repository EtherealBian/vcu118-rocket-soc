from pathlib import Path
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location('checkpoint_xdc', Path(__file__).resolve().parents[1] / 'scripts/review-mega-checkpoint-xdc.py')
xdc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xdc)


def parse(text, names=('runA', 'kitA', 'CfgA')):
    return xdc.commands(text.encode('ascii'), names)


class CheckpointCommands(unittest.TestCase):
    def test_waiver_only_ignores_timestamp(self):
        line = 'current_instance dbg_hub/inst\ncreate_waiver -type CDC -id {CDC-6} -from [get_pins a] -to [get_pins b] -user {vendor} -description {description} -timestamp "Fri Nov 27 12:34:56 GMT 2026"'
        parsed, counts = parse(line)
        self.assertEqual(counts, {('dbg_hub/inst', 'CDC', 'CDC-6'): 1})
        self.assertEqual((parsed, counts), parse(line.replace('Fri Nov 27 12:34:56', 'Thu Nov 26 01:02:03')))
        for old, new in [('CDC-6','CDC-15'), (' -type CDC',' -type DRC'), ('dbg_hub/inst','other/inst'), ('pins a', 'pins c'), ('pins b', 'pins d'), ('{vendor}', '{other}'), ('{description}', '{new}')]:
            with self.subTest(old=old):
                self.assertNotEqual(parse(line.replace(old,new))[0], parsed)
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            parse(line.replace(' GMT ', ' UTC '))

    def test_source_fields_keep_scope_order_filenames_and_target(self):
        fields = 'cfile:/b/runA/t.xdc rfile:/k/kitA/p.CfgA.shell.xdc rxprname:/t/.Xil/Vivado-123-host/dbg_hub_CV.0/ip.xpr scoped_inst:i order:EARLY other:/b/runA/keep'
        line = 'set_property SRC_FILE_INFO {' + fields + '} [current_design]'
        relocated = line.replace('/runA/t.xdc','/runB/t.xdc').replace('/kitA/p.CfgA.', '/kitB/p.CfgB.').replace('123-host','456-other')
        self.assertEqual(parse(line),parse(relocated, ('runB','kitB','CfgB')))
        for old, new in [('t.xdc','u.xdc'), ('scoped_inst:i','scoped_inst:j'), ('EARLY','LATE'), ('other:/b/runA/keep','other:/b/runB/keep'), ('dbg_hub_CV.0','dbg_hub_CV.1'), ('ip.xpr','x.xpr')]:
            with self.subTest(old=old): self.assertNotEqual(parse(line),parse(line.replace(old,new)))
        with self.assertRaisesRegex(ValueError, 'metadata'): parse(line.replace('current_design', 'get_cells top'))

    def test_operational_commands_and_order_are_never_normalized(self):
        a='create_clock -period 5.714 [get_ports clk]'
        b='set_false_path -to [get_cells /runA/d]'
        self.assertEqual(parse(a+'\n'+b),parse('# input\n'+a+'\n\n'+b+'\n'))
        for changed in [b+'\n'+a,a+'\n'+b.replace('runA','runB'),a.replace('5.714','10.000')+'\n'+b,a+'\n'+b+'\n'+b]:
            self.assertNotEqual(parse(a+'\n'+b),parse(changed))
