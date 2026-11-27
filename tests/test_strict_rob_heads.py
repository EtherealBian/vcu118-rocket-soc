import runpy
from pathlib import Path
import struct
import unittest

D=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-rob-heads.py'))
GATE=D['gate']; HEAD=D['HEAD']; CENSUS=D['census']


def ticket(tick,slot): return tick*128+slot


class HeadGates(unittest.TestCase):
    def test_oldest_valid_lane_precedes_younger_block(self):
        # Lane 1 can pass; lane 2 is busy and stops lane 3. This is an
        # architectural idle edge only if the physical commit was not architectural.
        k=ticket(8,9); word=2|(14<<5)|(4<<9)|(2<<17)
        self.assertEqual(GATE(12,k,word),'nonarchitectural_commit')
        for bad in (word^(2<<17),word|(8<<17),word|(1<<9),word|(1<<23)):
            with self.assertRaises(ValueError):GATE(12,k,bad)
        for wrong in (ticket(8,10),ticket(12,9),0):
            with self.assertRaises(ValueError):GATE(12,wrong,word)

    def test_overlapping_stops_and_empty_row(self):
        k=ticket(8,0)
        self.assertEqual(GATE(10,k,(1<<5)|(1<<9)|(1<<13)|(1<<21)|(1<<22)),'global+csr+exception+busy')
        self.assertEqual(GATE(10,0,7),'no_valid_head_lane')
        with self.assertRaises(ValueError):GATE(10,k,0)

    def test_gaps_on_edges_not_instructions(self):
        # Two commits on the left fence, then two on the right. Ticket for the
        # next committed instruction is dispatched at edge 11, not before it.
        a,b,c,d=(ticket(8,0),ticket(8,1),ticket(11,4),ticket(11,5))
        pcs=struct.pack('<4I',16,20,24,28); tickets=struct.pack('<8I',10,a,10,b,14,c,14,d)
        empty=HEAD.pack(11,0,1); busy=1|(1<<5)|(1<<9)
        head=empty+HEAD.pack(12,c,busy)+HEAD.pack(13,c,busy)
        go=lambda h:CENSUS(pcs,tickets,h,{c:(13,24)},[10,14]); res=go(head)
        self.assertEqual((res['hot_cycle_span'],res['idle_edges'],res['next_ticket_is_busy_head']),(4,3,2))
        self.assertEqual(res['next_instruction_dispatch'],dict(previously_dispatched=2,not_previously_dispatched=1))
        self.assertEqual(res['top_busy_heads'][0]['oldest_busy_edges_with_own_b2'],2)
        # Legal different generation of the same circular slot is NOT the next ticket.
        other=go(HEAD.pack(11,ticket(7,4),busy)+HEAD.pack(12,c,busy)+HEAD.pack(13,c,busy))
        with self.assertRaises(ValueError):go(empty+HEAD.pack(12,ticket(7,4),busy)+HEAD.pack(13,c,busy))
        self.assertEqual(other['other_ticket_is_busy_head'],1)
        for bad in (head[:-1],head[:-12],head[12:],empty+head,head+empty):
            with self.assertRaises(ValueError):go(bad)
        with self.assertRaises(ValueError):CENSUS(pcs,tickets,head,{c:(13,28)},[10,14])

    def test_only_taken_consecutive_loop_bodies(self):
        loop=D['LOOP']; seq=(loop[-1],*loop,loop[-1]+2)
        pcs=struct.pack('<7I',*seq)
        ticks=b''.join(struct.pack('<II',100+i,ticket(80+i,i)) for i in range(7))
        res=D['loop_intervals'](pcs,ticks,{ticket(80,0)})
        self.assertEqual((res['taken'],res['fallthrough'],res['taken_with_own_b2']),(1,1,1))
        self.assertEqual(res['branch_to_branch_retirement']['sum_cycles'],5)
        self.assertEqual(res['branch_to_branch_dispatch']['exactly_five'],1)
        for bad in (pcs[:-4],struct.pack('<7I',seq[0],seq[1],seq[3],seq[2],*seq[4:])):
            with self.assertRaises(ValueError):D['loop_intervals'](bad,ticks,{})
