#!/usr/bin/env python3
"""Boot the optional lab image on QEMU virt, check its ELF hash and both benchmark seed sets.
Do not use QEMU throughput as a VCU118 performance number.
"""
import argparse,hashlib,importlib.util,json,os,re,secrets,selectors,subprocess,tempfile,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('cmcheck',Path(__file__).with_name('review-coremark.py'));cm=importlib.util.module_from_spec(spec);spec.loader.exec_module(cm)
p=argparse.ArgumentParser(description=__doc__);p.add_argument('firmware',type=Path);p.add_argument('elf',type=Path);p.add_argument('out',type=Path);p.add_argument('--profile',choices=tuple(cm.PROFILES),default='baseline');a=p.parse_args();a.out.mkdir(); nonce=secrets.token_hex(7)
q=Path(os.getenv('VCU_TOOLS',Path.home()/'.local/share/vcu118-tools'))/'qemu';env=dict(os.environ);env['LD_LIBRARY_PATH']=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH','')
args=[q/'usr/bin/qemu-system-riscv64','-machine','virt','-m','256M','-smp','1','-nographic','-monitor','none','-bios',a.firmware.resolve()]
portable=a.profile=='g15-gc-lto'
if portable:
    # The pinned QEMU 4.2.1 has named RV64GC models but no zba/zbb property.
    # Do not infer illegal instructions from a model name or /proc/cpuinfo alone.
    cpu='rv64gcsu-v1.10.0';args.extend(['-cpu',cpu]);src=Path(__file__).resolve().parents[1]/'software/cpu-window/qemu-isa-probe.S'
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp);cc=q.parent/'bootlin/bin/riscv64-linux-';elf=t/'isa.elf';rawbin=t/'isa.bin'
        subprocess.run([str(cc)+'gcc','-march=rv64imac_zicsr','-mabi=lp64','-mcmodel=medany','-fno-pie','-no-pie','-static','-nostdlib','-Wl,--build-id=none,--no-relax,-Ttext=0x80000000',src,'-o',elf],check=True)
        subprocess.run([str(cc)+'objcopy','-O','binary',elf,rawbin],check=True)
        control=subprocess.check_output([args[0],'-M','virt','-cpu',cpu,'-smp','1','-m','256M','-bios',rawbin,'-nographic','-monitor','none'],env=env,stderr=subprocess.STDOUT,timeout=8)
        if control!=b'ISA_CONTROL_PASS addi=7 sh1add=illegal andn=illegal\n': raise ValueError('ISA negative execution control failed: '+repr(control))
        control_id=hashlib.sha256(rawbin.read_bytes()).hexdigest()
raw=bytearray(); end=time.monotonic()+240
with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0,env=env) as proc, selectors.DefaultSelector() as sel, (a.out/'uart.txt').open('xb') as log:
    sel.register(proc.stdout,selectors.EVENT_READ)
    def wait(pattern):
        while time.monotonic()<end:
            if re.search(pattern,raw,re.M):return
            if not sel.select(.3):continue
            s=os.read(proc.stdout.fileno(),16384)
            if not s:raise RuntimeError('guest closed console')
            raw.extend(s);log.write(s);log.flush()
            if len(raw)>196608 or b'Kernel panic' in raw:raise RuntimeError('guest failed')
        raise TimeoutError(str(pattern))
    def send(s):proc.stdin.write((s+'\n').encode());proc.stdin.flush()
    try:
        wait(rb'^# $')
        for mark in [b'VCU118_INITRAMFS_READY',b'SOC_CHECK_PASS bytes=16777216',b'LINUX_DOT4_NO_PLATFORM_DEVICE',b'LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d']:
            if not re.search(rb'^'+mark,raw,re.M):raise ValueError('not the expected optional system')
        if portable:
            send('cat /proc/cpuinfo; echo ISA_END_$((40+2))_'+nonce);wait(rb'^ISA_END_42_'+nonce.encode()+rb'\r?\n')
            isa=re.findall(rb'^isa\s*:\s*(rv64\w+)\r?$',raw,re.M)
            if len(isa)!=1 or re.search(rb'_(?:zba|zbb)(?:_|$)',isa[0]): raise ValueError('expected one hart without Zba/Zbb')
        send('echo CM_LIVE_$((6*7))_'+nonce);wait(rb'^(?:# )?CM_LIVE_42_'+nonce.encode()+rb'\r?\n');send(cm.command(nonce,0,a.profile));wait(rb'^CM_DONE_42_'+nonce.encode()+rb'\r?\n')
        result=cm.inspect(bytes(raw),nonce,hashlib.sha256(a.elf.read_bytes()).hexdigest(),0,profile=a.profile)
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
if portable: result.update(guest_isa=isa[0].decode(),qemu_cpu=cpu,isa_control=control.decode().strip(),isa_control_binary_sha256=control_id)
(a.out/'nonce.txt').write_text(nonce);result.update(scope='QEMU virt command and CRC validation only; not an FPGA benchmark',firmware_sha256=hashlib.sha256(a.firmware.read_bytes()).hexdigest());(a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('QEMU_COREMARK_CHECK_AND_VALIDATION_PASS')
