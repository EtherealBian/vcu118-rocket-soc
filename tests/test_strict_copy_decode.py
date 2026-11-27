"""Controls for the stock decode-edge witness; deliberately not a speedup test."""
from io import StringIO
from pathlib import Path
import runpy
import unittest

M = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-copy-decode.py'))
D, P, T = M['Dec'], M['PC'], M['TICKET']
ENTRY,COPY,LOAD,STORE,MOVE,BR = [M[k] for k in ('ENTRY','COPY','LOAD','STORE','MOVE','BR')]
MOV = D(20*128, 18, M['ENC'][COPY], 1,0,0,0,1,0,0,0,8,0,14,0,0,0,0)
LD = D(20*128+1, 18, M['ENC'][LOAD], 1,0,0,0,1,0,0,2,14,8,0,1,0,0,0)


def line(d): return ' '.join(map(str,d))+'\n'


def case(m=MOV,l=LD):
    pcs = (ENTRY, LOAD, STORE, MOVE, BR, COPY, LOAD, STORE, MOVE, BR, BR+2)
    e = LD._replace(key=12*128+2,tick=11)
    tickets = {1:e.key, 5:m.key, 6:l.key}
    raw = dict(pc=b''.join(P.pack(x) for x in pcs), tickets=b''.join(T.pack(60+i,tickets.get(i,0)) for i in range(len(pcs))))
    same = int(m.key>>7 == l.key>>7)
    anchor = dict(branches=2,taken=1,exits=1,same_dispatch=same,separate_dispatch=1-same)
    return raw, [line(d) for d in (e,m,l)], anchor


class StrictDecode(unittest.TestCase):
    def test_guard_and_individual_vetoes(self):
        hit = M['eligible']
        self.assertTrue(hit(MOV,LD))
        for field,val in [('exception',1),('sfb',1),('fp',1),('dst_valid',0),('dst_type',1),('src1_type',1),
                          ('src2_type',2),('inst',MOV.inst|0x40000000),('src1',1),('dst',9),('src2',12)]:
            with self.subTest(copy=field): self.assertFalse(hit(MOV._replace(**{field:val}),LD))
        for field,val in [('exception',1),('sfb',1),('fp',1),('inst',LD.inst|0x20),('inst',LD.inst|0x7000),
                          ('ldq',0),('stq',1),('amo',1),('cmd',1),('src1_type',1),('dst_type',1),('src1',7)]:
            with self.subTest(load=field): self.assertFalse(hit(MOV,LD._replace(**{field:val})))
        self.assertFalse(hit(MOV, LD._replace(inst=0x0003b703,src1=7)))
        for dst,src in ((0,14),(8,0),(8,8)):
            m=MOV._replace(inst=(src<<20)|(dst<<7)|0x33,dst=dst,src2=src)
            self.assertFalse(hit(m,LD._replace(inst=(dst<<15)|0x3703,src1=dst)))

    def test_decode_is_not_dispatch(self):
        for l,cell,hits in [(LD,'yes_yes',1), (LD._replace(key=21*128+1),'yes_no',1),
                             (LD._replace(tick=19),'no_yes',0), (LD._replace(key=21*128+2),'no_no',0)]:
            with self.subTest(cell=cell):
                result=M['analyse'](*case(l=l)); self.assertEqual(result['adjacent_decode_by_adjacent_dispatch'][cell],1)
                self.assertEqual(result['guard_matches'],hits)
                self.assertEqual(result['counts']['entry_load_without_copy'],1)
        self.assertFalse(M['adjacent'](MOV._replace(key=20*128+3),LD._replace(key=21*128)))

    def test_match_is_not_just_the_two_pcs(self):
        a=M['analyse'](*case(l=LD._replace(ldq=0)))
        self.assertEqual(a['adjacent_decode_by_adjacent_dispatch']['yes_yes'],1)
        self.assertEqual(a['guard_matches'],0)

    def test_missing_duplicate_wrong_instruction_or_ticket(self):
        raw, rows, counts = case()
        for change in [rows[:-1], rows+[rows[-1]], rows[:2]+[line(LD._replace(inst=LD.inst+2))],
                       rows[:2]+[line(LD._replace(key=LD.key+1))], rows[:1]+rows[2:]+rows[1:2]]:
            with self.assertRaises(ValueError): M['analyse'](raw,change,counts)
        with self.assertRaises(ValueError): M['analyse'](raw,rows,dict(counts,taken=2))

    def test_invalid_record_domains(self):
        for s in [line(MOV)*2, line(LD)+line(MOV), line(MOV._replace(rvc=2)),line(MOV._replace(tick=20)),
                  line(MOV._replace(tick=0)),line(MOV._replace(key=1<<32)),line(MOV._replace(inst=-1)),
                  line(MOV).replace('0','０'), '1 2\n']:
            with self.assertRaises(ValueError): list(M['records'](StringIO(s)))
