from pathlib import Path
import runpy
import unittest

R=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-strict-left-load.py'))


class LeftLoad(unittest.TestCase):
    def setUp(self):
        self.text='\n'.join(['A 14 259 0 2 9 8192 8194','S 15 259 0 2 9 12290 0',
                            'T 16 259 0 2 9 12290 3','S 19 259 1 2 9 12290 0',
                            'T 20 259 1 2 9 12290 1','C 20 259 1 2 9 42 0'])

    def inspect(self,text):
        return R['inspect'](R['parse'](text)[259],2,22)

    def test_nacked_hit_and_successful_retry_are_distinct(self):
        a,r,h=self.inspect(self.text)
        self.assertEqual(h,{'nack_hit':1,'hit':1}); self.assertEqual(r.tick-a.tick,6)

    def test_forward_without_normal_s2(self):
        rows=self.text.splitlines()[:2]+['F 16 259 0 2 9 42 31']
        self.assertEqual(self.inspect('\n'.join(rows))[2],{'no_s2':1})

    def test_changed_page_lane_age_or_identity(self):
        for old,new in [('12290 3','12292 3'),('T 16 259 0','T 16 259 1'),
                        ('S 19','S 18'),('C 20','C 23'),('C 20 259 1 2 9','C 20 259 1 3 9'),
                        ('S 15','S 13'),('12290 1','12290 4'),('8192 8194','8192 8196'),
                        ('12290 0','8194 0')]:
            with self.subTest(old=old,new=new),self.assertRaises(ValueError): self.inspect(self.text.replace(old,new))

    def test_result_requires_matching_s2_hit_and_return_lane(self):
        rows=R['parse'](self.text)[259]; r=rows[-1]
        self.assertEqual(R['result_class'](rows,r),'same_lane_normal_s2_hit')
        self.assertEqual(R['result_class'](rows,r._replace(lane=0)),'other_cache_response')
        self.assertEqual(R['result_class'](rows,r._replace(kind='F')),'store_queue')

    def test_two_tickets_cannot_use_same_port(self):
        with self.assertRaises(ValueError): R['parse'](self.text+'\n'+self.text.splitlines()[-1].replace('259','260'))

    def test_changed_reaching_pointer(self):
        a,r,_=self.inspect(self.text); parent=r._replace(v=a.v,tick=a.tick-3)
        R['reaching'](parent,a)
        for bad in [parent._replace(v=a.v+8),parent._replace(tick=a.tick+1)]:
            with self.assertRaises(ValueError): R['reaching'](bad,a)
