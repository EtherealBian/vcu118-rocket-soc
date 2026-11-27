from pathlib import Path
import runpy
import struct
import unittest

D=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-reversal.py'))


class Reversal(unittest.TestCase):
    def fixture(self):
        pcs=(0x13b60,*D['LOOP'][1:],*D['LOOP'],D['BR']+2)
        # Two real iterations: enter at ld, then take the five-instruction body once.
        keys=[(5+i//4)*128+i for i in range(len(pcs))]
        keys[5],keys[6]=10*128+5,10*128+6
        ticks=(14,15,16,17,18,19,20,21,22,24,25)
        raw=dict(pc=struct.pack('<11I',*pcs),tickets=b''.join(struct.pack('<II',t,k) for t,k in zip(ticks,keys)))
        def event(kind,t,i,lane,a,b):return f'{kind} {t} {keys[i]} {lane} {a} {b}'
        text='\n'.join([event('A',12,1,0,32,32),event('L',14,1,1,48,1),event('M',16,5,2,0,48),
                        event('E',16,4,1,48,0),event('A',17,6,0,48,48),event('B',17,4,1,1,0),
                        event('W',18,4,0,0,0),event('L',19,6,0,0,1),event('E',21,9,3,0,0),
                        event('B',22,9,3,0,0),event('W',23,9,1,0,0)])
        head=D['H']['HEAD'].pack(17,keys[4],1|(1<<5)|(1<<9))
        ref=dict(top_busy_heads=[dict(pc=hex(D['BR']),retirements=2,oldest_busy_edges=1)],reversal_loop=dict(taken=1,fallthrough=1))
        return raw,text,head,{},ref

    def test_enter_then_follow_nonoverlapping_chain(self):
        r=D['analyse'](*self.fixture()); self.assertEqual(r['counts']['same_dispatch_two_one_two'],1)
        self.assertEqual(r['counts']['branches'],2);self.assertEqual(r['busy_head_edges_by_observed_phase']['from_execute_before_clear'],1)
        self.assertEqual(r['cycle_intervals']['load_to_load']['histogram'],{5:1})

    def test_wrong_values_even_when_direction_unchanged(self):
        raw,text,*rest=self.fixture()
        for old,new in [('2 0 48','2 0 40'),('1 48 0','1 56 0'),('0 48 48','0 56 56'),('1 1 0','1 0 0')]:
            self.assertIn(old,text)
            with self.assertRaises(ValueError): D['analyse'](raw,text.replace(old,new,1),*rest)

    def test_wrong_ticket_and_late_old_head_are_not_evidence(self):
        raw,text,head,red,ref=self.fixture(); key=(10<<7)+5
        bad=text.replace('M 16 '+str(key),'M 16 '+str(key-128)); self.assertNotEqual(bad,text)
        with self.assertRaises(ValueError): D['analyse'](raw,bad,head,red,ref)
        with self.assertRaises(ValueError): D['analyse'](raw,text,struct.pack('<I',18)+head[4:],red,ref)
        with self.assertRaises(ValueError): D['analyse'](raw,text,head,red,{**ref,'reversal_loop':{'taken':2,'fallthrough':1}})

    def test_duplicate_reordered_and_foreign_events(self):
        raw,text,*rest=self.fixture(); lines=text.splitlines()
        for bad in ('\n'.join([lines[0],*lines]),'\n'.join([lines[1],lines[0],*lines[2:]]),
                    text+'\nM 26 1300 1 0 48',text.replace('W 18','W 16')):
            with self.assertRaises(ValueError): D['analyse'](raw,bad,*rest)
