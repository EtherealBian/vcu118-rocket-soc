from itertools import count
from pathlib import Path
import runpy
import unittest

M = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/prove-aw-slot-select.py'))


def fixture():
    """Small netlist with the real port shapes; no board RTL needed for these tests."""
    bits = count(1)
    net = {'ports': {}, 'netnames': {}, 'cells': {}}
    ports, names, cells = net['ports'], net['netnames'], net['cells']

    def port(name, width, direction='input'):
        vec = [next(bits) for _ in range(width)]
        ports[name] = {'direction': direction, 'bits': vec}
        return vec

    def cell(key, typ, output, **connections):
        cells[key] = {'type': typ, 'connections': {pin: [bit] for pin, bit in connections.items()},
                      'port_directions': {pin: 'output' if pin == output else 'input' for pin in connections}}

    clock, = port('clock', 1)
    valid, = port('io_enq_valid', 1)
    for name, width in [('widx_widx_bin', 3), ('ready_reg', 1), ('_sink_valid_io_out', 1)]:
        vec = [next(bits) for _ in range(width)]
        names[name] = {'bits': vec}
        for bit in vec:
            cell('src'+str(bit), 'FDRE', 'Q', D=valid, C=clock, Q=bit, CE='1', R='0')
    select = names['widx_widx_bin']['bits'] + names['ready_reg']['bits'] + names['_sink_valid_io_out']['bits'] + [valid]
    for field, width in M['WIDTH'].items():
        port('io_enq_bits_'+field, width)
    for slot in range(8):
        en = next(bits); key = 'lut'+str(slot)
        cell(key, 'LUT6', 'O', O=en, **{'I'+str(i): b for i,b in enumerate(select)})
        cells[key]['parameters'] = {'INIT': format(1 << (56+M['SLOTS'].index(slot)), '064b')}
        for field, width in M['WIDTH'].items():
            qs = port(f'io_async_mem_{slot}_{field}', width, 'output')
            for j, q in enumerate(qs):
                cell(f'{slot}_{field}_{j}', 'FDRE', 'Q', D=ports['io_enq_bits_'+field]['bits'][j], Q=q, C=clock, CE=en, R='0')
    return net


class SlotMap(unittest.TestCase):
    def test_all_slots(self):
        r = M['topology'](fixture(), 'lut6')
        self.assertEqual(r['enable_logic_levels_by_slot'], [1]*8)
        self.assertEqual(r['payload_direct_dq_bits'], 488)

    def test_swapped_address_bit_or_foreign_clock(self):
        for pin, src in [('D', 'io_enq_bits_addr'), ('C', 'io_enq_valid')]:
            n = fixture(); n['cells']['7_addr_31']['connections'][pin] = [n['ports'][src]['bits'][0]]
            with self.assertRaisesRegex(ValueError, 'direct unique D/Q'): M['topology'](n, 'lut6')

    def test_slot_alias(self):
        n = fixture()
        for k,c in n['cells'].items():
            if k.startswith('7_'): c['connections']['CE'] = n['cells']['lut6']['connections']['O']
        with self.assertRaisesRegex(ValueError, 'word alias'): M['topology'](n, 'lut6')

    def test_lut_init_or_pins(self):
        for fault in ('init', 'pin'):
            n = fixture(); c = n['cells']['lut7']
            if fault == 'init': c['parameters']['INIT'] = '1'*64
            else: c['connections']['I2'] = c['connections']['I0']
            with self.assertRaisesRegex(ValueError, 'wrong mapped slot INIT|wrong LUT pin order'): M['topology'](n, 'lut6')
