import importlib.util, pathlib, struct, tempfile, unittest, zlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('sd',Path(__file__).resolve().parents[1]/'scripts'/'make_sd.py'); sd=importlib.util.module_from_spec(spec); spec.loader.exec_module(sd)
class SD(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.d=Path(self.tmp.name); self.p=self.d/'payload.bin'; self.out=self.d/'card.img'
 def test_firmware_layout(self):
  data=bytes(range(251))*3; self.p.write_bytes(data); sd.make(self.p,self.out); S=512; last=self.out.stat().st_size//S-1
  with self.out.open('rb') as f:
   self.assertEqual(f.read(S)[510:],b'\x55\xaa'); tables=[]
   for hpos,back,tpos in [(1,last,2),(last,1,last-32)]:
    f.seek(hpos*S); h=bytearray(f.read(92)); self.assertEqual(bytes(h[:8]),b'EFI PART'); c,=struct.unpack_from('<I',h,16); h[16:20]=bytes(4); self.assertEqual(c,zlib.crc32(h)); self.assertEqual(struct.unpack_from('<QQ',h,24),(hpos,back)); f.seek(tpos*S); t=f.read(32*S); tables.append(t); self.assertEqual(zlib.crc32(t),struct.unpack_from('<I',h,88)[0]); self.assertEqual(struct.unpack_from('<QQ',t,32),(34,34+61440-1))
   self.assertEqual(*tables); f.seek(34*S); self.assertEqual(f.read(len(data)),data); self.assertEqual(f.read(2048),bytes(2048)); f.seek((34+61440)*S-1); self.assertEqual(f.read(1),b'\x00')
 def test_compact_new_image_preserves_both_gpt_copies_and_load_window(self):
  for n in (1,511,512,513,1311):
   with self.subTest(n=n):
    data=(bytes(range(251))*8)[:n];self.p.write_bytes(data);dest=self.d/f'compact-{n}.img';sd.make(self.p,dest,compact=True);count=(n+511)//512
    with dest.open('rb') as f:
     last=dest.stat().st_size//512-1
     for h,t in [(1,2),(last,last-32)]:
      f.seek(h*512);header=bytearray(f.read(92));header_crc=struct.unpack_from('<I',header,16)[0];header[16:20]=b'\0'*4;self.assertEqual(zlib.crc32(header),header_crc);f.seek(t*512);table=f.read(16384);self.assertEqual(zlib.crc32(table),struct.unpack_from('<I',header,88)[0]);self.assertEqual(struct.unpack_from('<QQ',table,32),(34,34+count-1))
     f.seek(34*512);self.assertEqual(f.read(n),data);self.assertEqual(f.read(512*count-n),b'\0'*(512*count-n))
 def test_bad_sizes_and_overwrite(self):
  self.p.touch();
  with self.assertRaises(ValueError): sd.make(self.p,self.out)
  with self.p.open('wb') as f: f.truncate(sd.LOAD+1)
  with self.assertRaises(ValueError): sd.make(self.p,self.out)
  self.p.write_bytes(b'x'); self.out.write_bytes(b'keep')
  with self.assertRaises(ValueError): sd.make(self.p,self.out)
  self.assertEqual(self.out.read_bytes(),b'keep')
if __name__=='__main__': unittest.main()
