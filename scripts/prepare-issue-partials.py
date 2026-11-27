#!/usr/bin/env python3
"""Retime the exact BOOM v3 issue-ready cone; never edit the upstream checkout."""
import argparse
from hashlib import sha256
from pathlib import Path

ORIGINAL_SHA='197641604b0f9dc096177a4fb5ae6bd5f8854dfa254c1915c85605a155bdac42'
BEFORE='''  val num_available = PopCount(will_be_available)
  for (w <- 0 until dispatchWidth) {
    io.dis_uops(w).ready := RegNext(num_available > w.U)
  }'''
AFTER='''  // Register 4-slot partials at the existing ready boundary. At cycle n+1
  // the sum equals PopCount(will_be_available(n)); no extra cycle or credit.
  val vcuAvailPartials = will_be_available.grouped(4).map(g => RegNext(PopCount(g))).toIndexedSeq
  def vcuSum(xs: Seq[UInt]): UInt = if (xs.size == 1) xs.head else {
    val (a,b) = xs.splitAt(xs.size / 2)
    vcuSum(a) +& vcuSum(b)
  }
  val num_available = vcuSum(vcuAvailPartials)
  for (w <- 0 until dispatchWidth) {
    io.dis_uops(w).ready := num_available > w.U
  }'''


def patch(original):
    if sha256(original).hexdigest()!=ORIGINAL_SHA or original.count(BEFORE.encode())!=1:
        raise ValueError('unreviewed BOOM issue-ready source')
    return original.replace(BEFORE.encode(), AFTER.encode())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    data=patch(a.source.read_bytes());a.out.parent.mkdir(exist_ok=True,parents=True)
    if a.out.exists() and a.out.read_bytes()!=data:raise ValueError('different overlay exists')
    if not a.out.exists():a.out.write_bytes(data)
    print('ISSUE_READY_PARTIALS_OVERLAY',sha256(data).hexdigest())
