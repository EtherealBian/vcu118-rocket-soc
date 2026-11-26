#!/usr/bin/env python3
"""Exercise Linux FAT reads/writes across two boots; QEMU only writes a fresh temporary image copy."""
import hashlib,os,pathlib,re,selectors,secrets,shutil,subprocess,sys,tempfile,time
root=pathlib.Path(__file__).resolve().parents[1]; P=pathlib.Path
if len(sys.argv)!=3:raise SystemExit('usage: qemu-storage.py firmware.bin two-partition.img')
bios,img=map(P,sys.argv[1:]); assert bios.is_file() and img.is_file() and img.stat().st_size==64<<20
q=P(os.environ.get('VCU_TOOLS',P.home()/'.local/share/vcu118-tools'))/'qemu'; exe=q/'usr/bin/qemu-system-riscv64';env=dict(os.environ);env['LD_LIBRARY_PATH']=f'{q}/usr/lib/x86_64-linux-gnu:{q}/lib/x86_64-linux-gnu:'+env.get('LD_LIBRARY_PATH','');nonce=secrets.token_hex(7); run=P(tempfile.mkdtemp(prefix='qemu-storage.',dir=root/'logs'))
with tempfile.TemporaryDirectory() as tmp:
 work=P(tmp)/'media.img';shutil.copyfile(img,work)
 for trial in [1,2]:
  args=[str(exe) if exe.exists() else 'qemu-system-riscv64','-machine','virt','-smp','1','-m','256M','-nographic','-monitor','none','-bios',str(bios),'-drive',f'file={work},format=raw,if=none,id=sd','-device','virtio-blk-device,drive=sd']
  with (run/f'uart-{trial}.txt').open('wb') as log,subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,bufsize=0) as proc:
   try:
    end=time.monotonic()+120; buf=b'';sent=False; sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
    while time.monotonic()<end:
     if not sel.select(1):continue
     chunk=os.read(proc.stdout.fileno(),8192)
     if not chunk:raise RuntimeError('UART closed')
     buf=(buf+chunk)[-80000:];log.write(chunk);log.flush()
     if b'Kernel panic' in buf: raise RuntimeError('panic')
     if not sent and b'SOC_CHECK_PASS bytes=16777216' in buf:
      ops=['mkdir /tmp/media','mount -t vfat /dev/vda2 /tmp/media','echo VCU118_DATA_PARTITION_V1 > /tmp/expected','cmp /tmp/expected /tmp/media/SEED.TXT']
      if trial==1:ops+=['echo '+nonce+' > /tmp/media/TEST.TXT','sync']
      ops+=['echo '+nonce+' > /tmp/expected','cmp /tmp/expected /tmp/media/TEST.TXT','echo STORAGE_$((20+22))_'+str(trial)]
      proc.stdin.write((' && '.join(ops)+'\n').encode());proc.stdin.flush();sent=True
     if sent and re.search(rb'(?:^|\n)(?:# )?STORAGE_42_'+str(trial).encode()+rb'\r?\n',buf):break
    else:raise RuntimeError('timeout: '+str(log.name))
   finally:
    proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
 with work.open('rb') as f,img.open('rb') as ref:assert f.read(32<<20)==ref.read(32<<20),'boot area modified'
 print('QEMU_STORAGE_PASS (virtio, not physical SPI) two boots, FAT write/read, boot sectors unchanged; evidence='+str(run))
