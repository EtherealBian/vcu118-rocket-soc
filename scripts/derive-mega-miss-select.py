#!/usr/bin/env python3
"""Isolate the integer-issue queue's same-cycle load-miss selection; never edit the stock kit."""
import argparse
from hashlib import sha256
from pathlib import Path
import re

KIT='b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959'
CORE,UNIT,SLOT='BoomCore','IssueUnitCollapsing_2','IssueSlot_32'
ALT='VcuIntMissSlot'
HASH={CORE:'815c0140d41682fafa4df0e9cfa6ae7d3138bdb63c6f7d29440b497409218b24', UNIT:'af0a6ce24faafd5867336e055cd6511cfb083d1deda7002e17e1ee5da2ec631f', SLOT:'822d63ca3907ef14e001b7b82f9f38c666d8b17cb296eeb755e65bd45ff832d7'}
MOV=re.compile(r'^(  wire +issue_slots_(\d+)_in_uop_valid = )([^;]+)(;[^\n]*)$', re.M)
SOURCE=r'_slots_(\d+)_io_will_be_valid'
DIS3='io_dis_uops_3_valid & ~io_dis_uops_3_bits_exception & ~io_dis_uops_3_bits_is_fence & ~io_dis_uops_3_bits_is_fencei'

def need(ok, msg):
    if not ok: raise ValueError(msg)

def one(s,a,b):
    need(s.count(a)==1,'missing/duplicate '+a);return s.replace(a,b)

def sealed(kit):
    lock=(kit/'CANDIDATE.sha256').read_bytes();need(sha256(lock).hexdigest()==KIT,'wrong stock board kit'); src={}
    for n,h in HASH.items():
        raw=(kit/'rtl'/(n+'.sv')).read_bytes();need(sha256(raw).hexdigest()==h and f'{h}  rtl/{n}.sv' in lock.decode().splitlines(),'wrong '+n);src[n]=raw.decode()
    need(re.findall(r'^  (IssueUnitCollapsing\w*) int_issue_unit \(',src[CORE],re.M)==[UNIT] and re.findall(r'^  (IssueUnitCollapsing\w*) mem_issue_unit \(',src[CORE],re.M)==['IssueUnitCollapsing_1'],'wrong owner')
    return src

def derive(src):
    unit,slot=src[UNIT],src[SLOT]; ports='  output        io_will_be_valid,'
    # Use a private slot type; the memory queue also instantiates the original.
    slot=one(slot,'module '+SLOT+'(','module '+ALT+'(');slot=one(slot,ports,'  output        vcu_base,\n  output        vcu_poison,\n'+ports)
    slot=one(slot,'  assign io_will_be_valid =', '''  // Select the resident source before consuming the common LSU miss.
  assign vcu_base = (|state) & ~(io_grant & (_may_vacate_T | _may_vacate_T_1 & p1 & p2 & ppred));
  assign vcu_poison = (|state) & (p1_poisoned | p2_poisoned);
  assign io_will_be_valid =''')
    for i in range(40):
        pin=f'_slots_{i}_io_will_be_valid'; decl='  wire        '+pin+';'
        unit=one(unit,decl,f'  wire vcu_base_{i}, vcu_poison_{i};\n'+decl)
        unit=one(unit,f'  {SLOT} slots_{i} (',f'  {ALT} slots_{i} (')
        site=f'    .io_will_be_valid               ({pin}),'
        unit=one(unit,site,f'    .vcu_base (vcu_base_{i}),\n    .vcu_poison (vcu_poison_{i}),\n'+site)
    changed=[]
    def move(m):
        i=int(m[2]);ex=m[3];ids=list(map(int,re.findall(SOURCE,ex)));need(ids==list(reversed(range(i+1,min(i+5,40)))),'wrong source slots')
        if not ids: return m[0]  # destination 39 selects only dispatch inputs
        changed.append(i);base=re.sub(SOURCE,r'vcu_base_\1',ex); poison=re.sub(SOURCE,r'vcu_poison_\1',ex)
        # Dispatch eligibility does not depend on a speculative load miss.
        poison=re.sub(r'\bwill_be_valid_4[012]\b', "1'b0",poison)
        return (f'  wire vcu_moved_base_{i} = {base};\n  wire vcu_moved_poison_{i} = {poison};\n'
                + m[1]+f'vcu_moved_base_{i} | (io_ld_miss & vcu_moved_poison_{i})'+m[4])
    unit=MOV.sub(move,unit);need(changed==list(range(39)),'unexpected integer queue shape')
    return unit+'\n'+slot

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('kit',type=Path);p.add_argument('fresh',type=Path);a=p.parse_args();out=derive(sealed(a.kit));a.fresh.mkdir();(a.fresh/(UNIT+'.sv')).write_bytes(out.encode())
