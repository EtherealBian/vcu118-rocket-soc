#!/usr/bin/env python3
"""Build a local slice of the stock Mega 40-slot queue for a matched timing probe.
This omits the logic that creates per-slot availability and consumes ready.
"""
import argparse
from hashlib import sha256
from pathlib import Path
import re

PIN='af0a6ce24faafd5867336e055cd6511cfb083d1deda7002e17e1ee5da2ec631f'


def fixtures(data):
    if sha256(data).hexdigest()!=PIN:raise ValueError('unreviewed 40-slot Mega issue unit')
    text=data.decode(); pat=r"wire \[5:0\]\s+num_available\s*=\s*(.*?);"; (expr,)=re.findall(pat,text,re.S)
    seen=[]
    def leaf(hit):
        i=int(hit[1]);seen.append(i)
        if int(hit[2])!=i:raise ValueError('slot mismatch')
        return f'a[{i}]'
    leafpat=r'(?:\()?~_slots_(\d+)_io_will_be_valid(?: \| (?:~_slots_0_io_valid|\(\|[\w]+\))\))? & ~issue_slots_(\d+)_in_uop_valid'
    expr=re.sub(leafpat,leaf,expr)
    if seen!=list(range(40)) or not re.fullmatch(r"[\s\dah',{}+\[\]]+",expr):raise ValueError('unexpected popcount pattern')
    orig=re.findall(r'io_dis_uops_(\d+)_ready_REG <= ([^;]+);',text)
    if orig!=[('0','|num_available'),('1','|(num_available[5:1])'),('2',"num_available > 6'h2"),('3','|(num_available[5:2])')]:raise ValueError('changed threshold expressions')
    def sumtree(xs):
        if len(xs)==1:return xs[0]
        k=len(xs)//2;return '('+sumtree(xs[:k])+' + '+sumtree(xs[k:])+')'
    def make(name,body):
        return f'module {name}(input wire clk,input wire [39:0] available,output reg [3:0] ready);\n  reg [39:0] a; always @(posedge clk) a<=available;\n'+body+'  always @(posedge clk) ready<=credits;\nendmodule\n'
    control='  wire [5:0] num_available = '+expr+';\n  reg [3:0] credits;\n'+''.join(f'  always @(posedge clk) credits[{i}] <= {c};\n' for i,c in orig)
    candidate=''.join('  reg [2:0] g%d; always @(posedge clk) g%d <= %s;\n'%(j,j,sumtree([f"{{2'b0,a[{j*4+i}]}}" for i in range(4)])) for j in range(10))
    candidate+='  wire [5:0] num_available = '+sumtree([f"{{3'b0,g{i}}}" for i in range(10)])+';\n  wire [3:0] credits;\n'+''.join(f'  assign credits[{i}] = {c};\n' for i,c in orig)
    return make('issue_ref',control),make('issue_partial',candidate)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stock_issue_sv',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    ref,candidate=fixtures(a.stock_issue_sv.read_bytes());a.out.mkdir();(a.out/'issue_ref.sv').write_bytes(ref.encode());(a.out/'issue_partial.sv').write_bytes(candidate.encode())
