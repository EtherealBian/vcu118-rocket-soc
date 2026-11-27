import runpy
from pathlib import Path
import unittest

M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-route-pin-overlap.py'))
CPU=M['CPU']


def test_table():
    header='destination_clock\tkind\tslack_ns\tlogic_levels\tfrom\tto\n'
    # Some sinks recur in both corners; compare independently and never match just the source cell.
    rows=[f'{CPU}\t{k}\t{(r-8)/1000:.3f}\t2\tcell/a[1]/C\tdst/mem[{r}]/{port}' for k,port in [('max','D'),('min','CE')] for r in range(40)]
    return (header+'\n'.join(rows+['other\tmax\t-9.000\t1\tother/Q\tdst/mem[15]/CE'])+'\n').encode()


class RoutePinOverlapTests(unittest.TestCase):
    def test_exact_pin_not_launch_not_other_clock_or_corner(self):
        pins=['cell/a[1]/C','dst/mem[15]/D','dst/mem[115]/D','x/dst/mem[15]/D','dst/mem[0]/Q','dst/mem[16]/CE']
        o=M['join'](pins,test_table())
        for kind,rank,entry,preview in [('max',16,2,1),('min',17,6,0)]:
            s=o[kind];self.assertEqual((s['sample_size'],s['negative_in_sample'],s['exact_matches'],s['from_initial_preview']),(40,8,1,preview));self.assertEqual((s['matches'][0]['routed_rank'],s['matches'][0]['initial_list_row']),(rank,entry))

    def test_partial_duplicate_wrong_clock_and_out_of_order_are_not_empty_results(self):
        data=test_table()
        for bad in [data.replace(b'dst/mem[0]/D',b'dst/mem[1]/D'),data.replace(b'-0.008',b'0.999'), data.replace(CPU.encode(),b'other',1),data.replace(b'-0.008',b'NaN',1),data.replace(b'\tmin\t',b'\tmax\t',1)]:
            with self.subTest(bad=bad[:90]),self.assertRaises(ValueError):M['join']([],bad)

    def test_initial_native_count_preview_and_launch_pair(self):
        table='| Launch Setup Clock | Launch Hold Clock | Pin |\n'+''.join(f'| {CPU} | {CPU} | m/r[{i}]/D |\n' for i in range(6))
        preview='\n'.join(table.splitlines()[:6])+'\n'
        log='INFO: [Route 35-580] Design has 6 pins with tight setup and hold constraints.\n\nThe top 5 pins with tight setup and hold constraints:\n'+preview+'\nFile with complete list of pins: tight_setup_hold_pins.txt\n'
        self.assertEqual(M['initial'](log,table)[-1],'m/r[5]/D')
        for badlog,badtable in [(log.replace('has 6','has 7'),table),(log.replace('m/r[0]/D','m/r[0]/CE'),table),(log,table.replace('m/r[5]/D','m/r[3]/D')),(log,table.replace(f'| {CPU} |', '| JTCK |',1))]:
            with self.assertRaises(ValueError):M['initial'](badlog,badtable)
