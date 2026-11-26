import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('capture',ROOT/'scripts/verify-soc-capture.py'); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)

class CaptureTest(unittest.TestCase):
    def test_six_ordered_real_readbacks(self):
        rows=['VOLATILE_PROGRAM_START cable=fixture']+[f'PROGRAM_READBACK REGISTER.CONFIG_STATUS.SLR{i}.{k}={v}' for i in range(3) for k,v in [('BIT[14]_DONE_PIN',1),('BIT[00]_CRC_ERROR',0)]]+['VOLATILE_PROGRAM_AND_READBACK_PASS']
        c.check_program(['# VOLATILE_PROGRAM_AND_READBACK_PASS']+rows)
        for bad in (rows[:-1],rows+[rows[-1]], rows[:3]+rows[4:], [*rows[:2],rows[2][:-1]+'1',*rows[3:]]):
            with self.assertRaises(ValueError): c.check_program(bad)

    def test_nonce_from_shell_not_command_echo(self):
        n='0a0b0c0d0e0f22'; reply=f'BOARD_42_{n}\r\n'; cmd=f'# echo BOARD_$((40+2))_{n}\r\n'
        text='UART5_READY v1\r\nUART5_HANDOFF\r\nOpenSBI\r\nVCU118_INITRAMFS_READY\r\nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=3\r\n'+cmd+reply
        c.check_uart(text.encode(),'linux',n)
        for bad in (text.removesuffix(reply),text.replace('bytes=16777216','bytes=1677'),text.replace('HANDOFF','OTHER'),text+'Kernel panic',text.replace(reply,'old-session\r\n')):
            with self.assertRaises(ValueError): c.check_uart(bad.encode(),'linux',n)

    def test_oscheck_requires_guest_proof_before_prompt(self):
        nonce='abcd0000000042'; marker='LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d'
        sample='UART5_READY v1\nUART5_HANDOFF\nVCU118_INITRAMFS_READY\nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=1\n'+marker+'\n# uname\nBOARD_42_'+nonce+'\n'
        c.check_uart(sample.encode(),'linux-oscheck',nonce)
        for bad in (sample.replace(marker,'LINUX_OSCHECK_FAILED'),sample.replace(marker,''),sample.replace('128 fp','127 fp'),sample.replace(marker,'# echo '+marker),sample.replace(marker,'')+marker+'\n'):
            with self.assertRaises(ValueError):c.check_uart(bad.encode(),'linux-oscheck',nonce)

    def test_only_current_bare_epoch(self):
        text=b'UART5_READY v1\r\nUART5_HANDOFF\r\nVCU118_DIAG_START v1\r\nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r\n'
        c.check_uart(text,'bare',None)
        for bad in (text+text,text.replace(b'HANDOFF',b'OTHER'),text.replace(b'passes=2',b'passes=1')):
            with self.assertRaises(ValueError): c.check_uart(bad,'bare',None)

    def test_accelerator_required(self):
        n='ac132562bc132a'; prefix='UART5_READY v1\nUART5_HANDOFF\n'
        bare='DOT4_MMIO_START\nDOT4_MMIO_PASS vectors=257 protocol_errors_checked=2\n'
        d='LINUX_DOT4_PASS vectors=257 reserved_rejected=1'; init='VCU118_INITRAMFS_READY\nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=3\n'
        text=prefix+init+d+f'\n# echo BOARD_$((40+2))_{n}\nBOARD_42_{n}\n'
        c.check_uart((prefix+bare).encode(),'dot4',None);c.check_uart(text.encode(),'linux-dot4',n)
        for old,new in [(d,'LINUX_DOT4_NO_PLATFORM_DEVICE'),(d,'echo '+d),(d,d+'\nLINUX_DOT4_FAILED'),('vectors=257','vectors=256')]:
            with self.assertRaises(ValueError):c.check_uart(text.replace(old,new).encode(),'linux-dot4',n)
        with self.assertRaises(ValueError):c.check_uart((prefix+bare.split('\n',1)[1]).encode(),'dot4',None)
