from pathlib import Path
import copy
import gzip
import runpy
import unittest

M=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review-mega-linux-entry.py'))
CRC='BAD_CRC_STOP tick=883890 quiet_bits=20\n'
NEG=b'UART5_READY v1\r\nUART5_STOP CRC\r\n'
EVENTS=('ROM_HANDOFF tick=838329 wire=24 backing_preloaded=5604352 edge_intervals=9 ticks_per_bit=1519\n'
        'PROGRESS cycles=5000000 reads=80 writes=40\n'
        'PROGRESS cycles=10000000 reads=300 writes=120\n'
        'MRET_KERNEL tick=11700001 mepc=0x80200000 prv=3->1 mpp=1 satp_mode=0\n'
        'KERNEL_ENTRY_TL_GET tick=11700010 bytes=64\n'
        'ENTRY_WITNESS tick=11701000 s_arch_retired=259 reads=310 writes=124\n')
UART=b'\r\n'.join([b'UART5_READY v1',b'UART5_HANDOFF',b'',b'OpenSBI v1.5',b'Platform HART Count : 1',b'Platform Timer Device : aclint-mtimer @ 175000Hz',b'Domain0 Boot HART : 0',b'Domain0 Next Address : 0x0000000080200000',b'Domain0 Next Mode : S-mode'])

class EntryTests(unittest.TestCase):
    def check(self,crc=CRC,neg=NEG,events=EVENTS,uart=UART):return M['inspect'](crc,neg,events,uart,5604352)

    def test_early_or_late_get_both_need_registered_transition(self):
        self.assertEqual(self.check()['supervisor_arch_commits'],259)
        lines=EVENTS.splitlines(True);lines[3],lines[4]=lines[4].replace('11700010','11700000'),lines[3]
        self.assertLess(self.check(events=''.join(lines))['entry_tl_get_tick'],11700001)
        with self.assertRaises(ValueError):self.check(events=''.join(lines[:4]+lines[5:]))

    def test_rom_epoch_controls(self):
        for key,bad in [('neg',NEG[:-1]),('neg',NEG.replace(b'STOP CRC',b'HANDOFF')),('crc',CRC.replace('20','12')),('crc',CRC.replace('883890','10')),('uart',UART.replace(b'175000Hz',b'100000Hz')),('uart',UART.replace(b'Count : 1',b'Count : 2')),('uart',UART+b'\r\nUART5_HANDOFF'),('uart',UART.replace(b'OpenSBI v1.5',b'OpenSBI v1.5\r\nOpenSBI v1.5')),('uart',UART.replace(b'80200000',b'80400000')),('uart',UART.replace(b'S-mode',b'M-mode'))]:
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):self.check(**{key:bad})

    def test_rejects_bad_boundaries_and_nonmonotonic_model_progress(self):
        for a,b in [('5604352','5604360'),('ticks_per_bit=1519','ticks_per_bit=868'),('wire=24','wire=5604368'),('bytes=64','bytes=4'),('0x80200000','0x80400000'),('prv=3->1','prv=1->3'),('satp_mode=0','satp_mode=8'),('s_arch_retired=259','s_arch_retired=260'),('s_arch_retired=259','s_arch_retired=255'),('reads=310','reads=299'),('writes=120','writes=39'),('10000000','12000000'),('11701000','11700002'),('11700010','11700000'),('ENTRY_WITNESS','SECOND_HANDOFF')]:
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):self.check(events=EVENTS.replace(a,b))
        with self.assertRaises(ValueError):self.check(events=EVENTS.replace('PROGRESS cycles=5000000 reads=80 writes=40\n',''))

    def test_pair_rejects_shared_build_or_mismatched_outputs(self):
        common=['fw_payload.bin','Image','coremark-g15-gc-lto-ooo-strict.elf','prefix.frame','crc.frame','mega_linux_entry.cpp','rocket_chiptop.cpp'];keys=['model','CANDIDATE.sha256','VChipTop__ALL.a','VChipTop___024root.h']
        def row(role):return dict(role=role,hashes={**{k:k for k in common},**{k:role+k for k in keys}},evidence={'crc.events':'h'},witness=self.check(),embedded={'member': 'strict'})
        a,b=row('stock'),row('lvt');M['pair'](a,b)
        for k in keys[:3]+common:
            c=copy.deepcopy(b);c['hashes'][k]=a['hashes'][k] if k in keys else 'other'
            with self.subTest(key=k),self.assertRaises(ValueError):M['pair'](a,c)
        for k in ['evidence','witness','embedded']:
            c={**b,k:{}}
            with self.subTest(key=k),self.assertRaises(ValueError):M['pair'](a,c)


class EmbeddedBenchmarkTests(unittest.TestCase):
    def file(self, name, data=b'', mode=0o100755, uid=0, links=1):
        fields = (1,mode,uid,0,links,0,len(data),0,0,0,0,len(name)+1,0)
        hdr = b'070701'+b''.join(('%08x'%v).encode() for v in fields)+name+b'\0'
        return hdr + bytes(-len(hdr)%4) + data + bytes(-len(data)%4)

    def test_member_metadata_boundaries_and_exact_bytes(self):
        strict=M['STRICT']; directory=self.file(b'bin',mode=0o40755,links=2)
        target=self.file(strict,b'ELF!'); trailer=self.file(b'TRAILER!!!',mode=0)
        def run(archive,delta=0,extra=b''):
            stream=gzip.compress(archive)+extra
            image=stream+bytes(4)+(len(stream)+delta).to_bytes(8,'little')
            return M['embedded_benchmark'](image,b'ELF!',0,len(image)-8)
        good=directory+target+trailer+bytes(4)
        self.assertEqual(run(good)['entries'],2)
        for archive in (target+trailer, directory+trailer, directory+target+target+trailer,
                        directory+self.file(strict,b'elf!')+trailer,
                        directory+self.file(strict,b'ELF!',0o120777)+trailer,
                        directory+self.file(strict,b'ELF!',uid=1)+trailer,
                        directory+self.file(strict,b'ELF!',links=2)+trailer,
                        self.file(b'bin',b'other',0o120777)+target+trailer,
                        directory+target+trailer+b'x', good[:-40],
                        directory+target+self.file(b'./'+strict,b'other')+trailer,
                        bytes(2**20)+good):
            with self.assertRaises(ValueError):run(archive)
        for delta,extra in ((-1,b''),(1,b''),(0,gzip.compress(b'second'))):
            with self.assertRaises(ValueError):run(good,delta,extra)
