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

    def test_only_current_bare_epoch(self):
        text=b'UART5_READY v1\r\nUART5_HANDOFF\r\nVCU118_DIAG_START v1\r\nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r\n'
        c.check_uart(text,'bare',None)
        for bad in (text+text,text.replace(b'HANDOFF',b'OTHER'),text.replace(b'passes=2',b'passes=1')):
            with self.assertRaises(ValueError): c.check_uart(bad,'bare',None)
