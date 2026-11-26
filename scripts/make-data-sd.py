#!/usr/bin/env python3
"""Build a NEW regular-file two-partition image; never open block devices for writing."""
import hashlib,os,shutil,subprocess,sys,tempfile,uuid
from pathlib import Path
from make_sd import make,SECTOR,START,LOAD
DATA_LBA=65536; DATA_SECTORS=57344
SEED=b'VCU118_DATA_PARTITION_V1\n'
def two_partition(payload,dest):
 dest=Path(dest);payload=Path(payload);r=dest.resolve()
 if dest.suffix!='.img' or dest.is_symlink() or dest.exists() or Path('/dev') in r.parents:raise ValueError('new .img file required')
 with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
  td=Path(temp); img=td/'sd.img'; fat=td/'data.fat'; seed=td/'SEED.TXT'; make(payload,img)
  partuuid=str(uuid.uuid5(uuid.NAMESPACE_URL,'vcu118/data/'+hashlib.sha256(payload.read_bytes()).hexdigest()))
  def call(*a):subprocess.run(list(map(str,a)),check=True)
  call('sgdisk',f'--new=2:{DATA_LBA}:{DATA_LBA+DATA_SECTORS-1}','--typecode=2:0700','--change-name=2:VCU118 data',f'--partition-guid=2:{partuuid}',img)
  with fat.open('xb') as f:f.truncate(DATA_SECTORS*SECTOR)
  call('mkfs.fat','--invariant','-F','16','-n','VCUDATA',fat);seed.write_bytes(SEED);os.utime(seed,(1733011200,1733011200));call('mcopy','-m','-i',fat,seed,'::SEED.TXT')
  with img.open('r+b')as dst, fat.open('rb')as src:dst.seek(DATA_LBA*SECTOR);shutil.copyfileobj(src,dst)
  call('sgdisk','-v',img)
  with img.open('rb')as disk:
   disk.seek(START*SECTOR); window=disk.read(LOAD); data=payload.read_bytes();assert window[:len(data)]==data and not any(window[len(data):]); disk.seek(DATA_LBA*SECTOR);assert disk.read(512)==fat.read_bytes()[:512]
  # Exclusive destination creation, including at the last step; no implicit device opening.
  with dest.open('xb')as w,img.open('rb')as src:shutil.copyfileobj(src,w)
 print('TWO_PARTITION_SD_READY',dest,hashlib.sha256(dest.read_bytes()).hexdigest())
if __name__=='__main__':
 if len(sys.argv)!=3:raise SystemExit('usage: make-data-sd.py fw_payload.bin output.img')
 two_partition(*sys.argv[1:])
