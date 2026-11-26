"""Fail-closed checks for the generated bus cut and simulator/kit provenance."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


def load(name):
    p = Path(__file__).resolve().parents[1]/'scripts'/(name+'.py')
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


buffer = load('check-debug-buffer'); model = load('check-model-kit')


class BufferChecks(unittest.TestCase):
    state = '''reg wrap; reg wrap_1; reg maybe_full;
    wire ptr_match = wrap == wrap_1; wire empty = ptr_match & ~maybe_full;
    wire full = ptr_match & maybe_full; assign io_enq_ready = ~full;
    assign io_deq_valid = ~empty;'''

    def test_queue_rejects_flow_pipe_and_missing_state(self):
        buffer.queue_state(self.state)
        for old,new in [('~empty;', '~empty | io_enq_valid;'), ('~full;', '~full | io_deq_ready;'), ('reg wrap;', '')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                buffer.queue_state(self.state.replace(old, new))

    def test_instance_clock_reset_and_unique_bindings(self):
        src='  Q fifo (.clock(clock), .reset(reset), .data(x));'
        self.assertEqual(buffer.instance(src, 'Q', 'fifo')[1]['data'],'x')
        for v in [src.replace('reset(reset)','reset(clock)'),src.replace('.data(x)', '.data(x),.data(y)'),src+'\n'+src]:
            with self.subTest(v=v),self.assertRaises(ValueError): buffer.instance(v,'Q','fifo')


class ModelChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name).resolve(); cls.k=root/'kit'; cls.o=root/'obj'; cls.k.mkdir(); cls.o.mkdir()
        (cls.k/'rtl').mkdir(); names=['rtl/file%03d.sv'%i for i in range(300)]
        for n in names: (cls.k/n).write_bytes(n.encode())
        manifest=cls.k/'sources.f'; manifest.write_bytes(('\n'.join(names)+'\n').encode()); cls.rows=[]; sums=[]
        for n in ['sources.f',*names]:
            p=cls.k/n; st=p.stat(); args=[st.st_size,st.st_ino,*divmod(st.st_ctime_ns,10**9),*divmod(st.st_mtime_ns,10**9)]
            cls.rows.append('S '+' '.join(map(str,args))+' "'+p.as_posix()+'"'); sums.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+n)
        cls.cmd='C "--top-module ChipTop -F '+"'"+manifest.as_posix()+"'"+'"'
        cls.dat=cls.o/'VChipTop__verFiles.dat'; cls.sums=cls.k/'CANDIDATE.sha256'; cls.good='\n'.join(sums)+'\n'

    def setUp(self):
        self.write(self.cmd,self.rows); self.sums.write_text(self.good)

    def write(self,cmd,rows): self.dat.write_text('\n'.join([cmd,*rows])+'\n')

    def test_current_inputs_pass(self): model.check(self.o,self.k)

    def test_wrong_or_repeated_manifest_rejected(self):
        for cmd in [self.cmd.replace('sources.f','alternate.f'),self.cmd.replace(' -F ',' -F x -F '),'C "-F"']:
            self.write(cmd,self.rows)
            with self.subTest(cmd=cmd),self.assertRaises(ValueError): model.check(self.o,self.k)

    def test_missing_or_replaced_input_rejected(self):
        for rows in [self.rows[:-1],self.rows+[self.rows[1]],['S 0 0 0 0 0 0 '+'"'+self.rows[0].split(' "',1)[1],*self.rows[1:]]]:
            self.write(self.cmd,rows)
            with self.assertRaises(ValueError): model.check(self.o,self.k)

    def test_corrupt_or_duplicate_digest_rejected(self):
        for text in ['0'*64+self.good[64:],self.good+self.good.splitlines()[0]+'\n']:
            self.sums.write_text(text)
            with self.assertRaises(ValueError): model.check(self.o,self.k)


if __name__ == '__main__': unittest.main()
