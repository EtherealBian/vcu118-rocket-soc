#!/usr/bin/env python3
"""Check the generated three-wide D-cache's actual one-edge MSHR way-select cone."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


MODULE = 'BoomNonBlockingDCache'
TAG = 's2_tag_match_way_0'
REPL = 's2_replaced_way_en_REG'
PIN = 'io_req_0_bits_way_en'
STOCK = '97f5764f97a945d4b90b7ea9a1711942a40c8a6ceff16844e3574605ff882032'


def only(seq, label):
    seq = list(seq)
    if len(seq) != 1:
        raise ValueError('expected exactly one '+label)
    return seq[0]


class Cone:
    def __init__(self, xml):
        root = ET.parse(xml)
        self.mod = only((m for m in root.iter('module') if m.get('name') == MODULE), MODULE)
        self.dt = {n.get('id'): n for n in root.findall('.//typetable/basicdtype')}
        self.parent = {c:p for p in self.mod.iter() for c in p}
        self.drivers = {}
        for n in self.mod.iter():
            if n.tag in ('assigndly', 'contassign', 'assign') and len(n) == 2 and n[1].tag == 'varref':
                self.drivers.setdefault(n[1].get('name'), []).append(n)
        inst = only((i for i in self.mod.findall('instance') if i.get('name') == 'mshrs' and i.get('defName') == 'BoomMSHRFile'), 'MSHR instance')
        self.pin = only(only((p for p in inst.findall('port') if p.get('name') == PIN and p.get('direction') == 'in'), PIN), 'pin expression')

    def width(self, n):
        t = self.dt[n.attrib['dtype_id']]
        if t.get('name') not in ('logic', 'bit') or (t.get('signed') and n.tag != 'const') or int(t.get('right', '0')) != 0:
            raise ValueError('expected unsigned descending logic')
        return 1+int(t.get('left','0'))

    def reg_rhs(self, name):
        d = only(self.drivers.get(name, []), 'driver of '+name)
        p = self.parent[d]
        while p.tag == 'begin': p = self.parent[p]
        if d.tag != 'assigndly' or p.tag != 'always' or self.parent[p] is not self.mod:
            raise ValueError('not an unconditional module-scope register: '+name)
        sense = only(p.findall('sentree'), 'sensitivity list'); event = only(sense,'clock event')
        clk = only(event, 'clock')
        if (event.tag,event.get('edgeType'),clk.tag,clk.get('name')) != ('senitem','POS','varref','clock'):
            raise ValueError('wrong clock or extra event')
        if self.width(d[0]) != self.width(d[1]): raise ValueError('register truncation or extension')
        return d[0]

    def ast(self, n, shared=None, seen=()):
        # Inline only synthesizer temporaries below this cut. Never cross a flop.
        if n.tag == 'varref' and shared is not None and n.get('name') not in shared:
            k = n.get('name'); d = only(self.drivers.get(k,[]), 'combinational source of '+k)
            if (k in seen or d.tag != 'contassign' or self.parent[d] is not self.mod
                    or self.width(n) != self.width(d[0])):
                raise ValueError('state, conditional assignment or cycle inside cut: '+k)
            return self.ast(d[0], shared, (*seen,k))
        # Compare data attributes as well as type widths; omit only compiler location and type ID.
        attrs = tuple(sorted((k,v) for k,v in n.attrib.items() if k not in ('loc','dtype_id')))
        if self.dt[n.attrib['dtype_id']].get('signed'): attrs += (('signed','true'),)
        children = tuple(self.ast(c,shared,seen) for c in n)
        if n.tag == 'sel' and len(children) == 3 and n[1].tag == n[2].tag == 'const':
            # Verilator may widen just the literal offset (e.g. signed 6'hc vs 32'hc).
            # Only canonicalize static, nonnegative, wholly in-range slices.
            lo,count = (nonnegative(c) for c in children[1:]); width = self.width(n)
            if count != width or lo + count > children[0][1]: raise ValueError('out-of-range slice')
            return ('constant_slice', width, (('lo',lo),), children[:1])
        return (n.tag, self.width(n), attrs, children)


def var(name,width): return ('varref',width,(('name',name),),())


def replace(node, cuts):
    if node in cuts: return cuts[node]
    op,w,attrs,args = node
    return (op,w,attrs,tuple(replace(c,cuts) for c in args))


def nonnegative(node):
    op,w,attrs,k = node; attrs = dict(attrs)
    m = re.fullmatch(r"(\d+)'h([0-9a-fA-F]+)",attrs.get('name',''))
    if op != 'const' or k or not m or int(m[1]) != w: raise ValueError('expected a constant bitvector')
    v = int(m[2],16)
    if v >= 1 << w or (attrs.get('signed') and v >= 1 << (w-1)): raise ValueError('negative or truncated literal')
    return v


def lsb_first(node):
    """Bit identities, not values: accept only wiring and unsigned zero extension."""
    op,w,a,k = node; attrs=dict(a)
    if attrs.get('signed'): raise ValueError('signed replacement-index wiring')
    if op=='varref' and not k: return [(node,i) for i in range(w)]
    if op=='const': return [(nonnegative(node)>>i)&1 for i in range(w)]
    if op=='concat' and len(k)==2 and k[0][1]+k[1][1]==w: return lsb_first(k[1])+lsb_first(k[0])
    if op=='extend' and len(k)==1 and int(attrs['width'])==w and int(attrs['widthminv'])==k[0][1] and w>=k[0][1]:
        return lsb_first(k[0])+[0]*(w-k[0][1])
    raise ValueError('unknown replacement-index wiring')


def match_shift_index(node, old):
    op,w,a,k=node
    if op=='shiftl' and len(k)==2:
        bits = lsb_first(k[1]); expect = lsb_first(old)
        if len(bits)<len(expect) or bits!=expect+[0]*(len(bits)-len(expect)):
            raise ValueError('changed shift index value or bit order')
        return op,w,a,(k[0],var('INDEX',3))
    return op,w,a,tuple(match_shift_index(c,old) for c in k)


def evaluator(node):
    op,w,atts,nodes = node; attr=dict(atts); args=[evaluator(a) for a in nodes]
    if op=='varref' and node==var('MASK',8): return lambda m,r:m
    if op=='varref' and node==var('INDEX',3): return lambda m,r:r
    if op=='const' and not args:
        match=re.fullmatch(r"(\d+)'h([0-9a-fA-F]+)",attr.get('name',''))
        if match and int(match[1])==w and int(match[2],16)<2**w:
            value=int(match[2],16); return lambda m,r:value
    if op=='redor' and len(args)==1 and w==1: return lambda m,r:int(bool(args[0](m,r)))
    if op=='cond' and len(args)==3 and [n[1] for n in nodes]==[1,w,w]:
        return lambda m,r:args[1 if args[0](m,r) else 2](m,r)
    if op=='shiftl' and len(args)==2 and nodes[0][1]==w:
        return lambda m,r:(args[0](m,r)<<args[1](m,r)) & ((1<<w)-1)
    raise ValueError('unknown leaf/operator in reduced way expression: '+op+' '+str(atts))


def check_cones(ref, new):
    tag,idx = [ref.reg_rhs(n) for n in (TAG,REPL)]
    leaves = {n.get('name') for x in (tag,idx) for n in x.iter('varref')}
    if (ref.width(tag),ref.width(idx),ref.width(ref.pin),new.width(new.pin))!=(8,3,8,8):
        raise ValueError('changed interface widths')
    mt,rt=ref.ast(tag),ref.ast(idx)
    reference=replace(ref.ast(ref.pin),{var(TAG,8):var('MASK',8),var(REPL,3):var('INDEX',3)})
    if ref.pin.tag!='cond' or new.pin.tag!='varref': raise ValueError('MUX has not moved across the boundary')
    pre=new.reg_rhs(new.pin.attrib['name'])
    # Exact, width-aware equality of the old tag/replacement D inputs and the new operands,
    # including metadata way order, replay/writeback overrides and LFSR index bit order.
    candidate=match_shift_index(replace(new.ast(pre,leaves),{mt:var('MASK',8)}),rt)
    orig,changed=evaluator(reference),evaluator(candidate)
    vectors=[(m,r) for m in range(256) for r in range(8)]
    def expected(m,r): return m or 1<<r
    if any(orig(m,r)!=expected(m,r) or changed(m,r)!=orig(m,r) for m,r in vectors):
        raise ValueError('at least one output mismatches on the first edge')
    # Check both negative controls against the very same extracted candidate, after warm-up.
    m,r=next((m,r) for m,r in vectors if m and m&(m-1) and (changed(m,r)&127)!=orig(m,r))
    prev,now=(0,7),(3,2)
    if changed(*prev)==orig(*now):raise ValueError('late-edge control failed to differ')
    return dict(shared_mask_bits=8,shared_index_bits=3,single_edge_vectors=len(vectors),
                multi_hot_vectors=sum(1 for m,_ in vectors if m&(m-1)),
                high_bit_dropped_witness=dict(mask=m,index=r,reference=orig(m,r),mutant=changed(m,r)&127),
                extra_register_witness=dict(previous=list(prev),current=list(now),reference=orig(*now),mutant=changed(*prev)))


def compare_inputs(ref, new):
    # Ignore the config class in the filenames of only the two generated memory wrappers.
    maps = []
    for kit,cfg in ((ref,'PerfLargeBoomVCU118Config'),(new,'PerfEarlyWayBoomVCU118Config')):
        entries=(kit/'sources.f').read_text().splitlines(); mapping={}
        for name in entries:
            if not re.fullmatch(r'rtl/[A-Za-z0-9_.-]+\.s?v',name): raise ValueError('unexpected source path')
            prefix='rtl/chipyard.fpga.vcu118.VCU118FPGATestHarness.'+cfg+'.'
            key=name.replace(cfg+'.','CONFIG.') if name in (prefix+'top.mems.v',prefix+'model.mems.v') else name
            if key in mapping: raise ValueError('repeated HDL')
            mapping[key]=kit/name
        pairs=[r.split('  ',1) for r in (kit/'CANDIDATE.sha256').read_text().splitlines()]
        expected=set(entries)|{'sources.f','board.dts','rom/sdboot.bin','rom/sdboot.elf','config.scala'}
        if {n for h,n in pairs}!=expected or len(pairs)!=len(expected) or len(mapping)<300: raise ValueError('incomplete input manifest')
        maps.append(mapping)
    x,y=maps
    if list(x)!=list(y): raise ValueError('changed HDL compilation order')
    for k in ('board.dts','rom/sdboot.elf','rom/sdboot.bin'):
        if (ref/k).read_bytes()!=(new/k).read_bytes(): raise ValueError('changed boot inputs')
    only_locations={'rtl/'+k+'.sv' for k in ('BoomDuplicatedDataArray','BoomProbeUnit','BoomWritebackUnit')}
    def stripped(line):
        # Match a trailing generated annotation outside of string literals.
        for m in re.finditer(rb'"(?:[^"\\]|\\.)*"|//',line):
            if m[0]==b'//':
                if re.fullmatch(rb'// @\[[^\r\n]+\]',line[m.start():]): return line[:m.start()]
                break
        return line
    types={'byte_identical':0,'location_annotations_only':[],'changed_logic':[]}
    for k in x:
        a,b=x[k].read_bytes(),y[k].read_bytes()
        if a==b: types['byte_identical']+=1
        elif k in only_locations and list(map(stripped,a.splitlines()))==list(map(stripped,b.splitlines())):
            types['location_annotations_only'].append(k.split('/')[-1])
        elif k=='rtl/'+MODULE+'.sv': types['changed_logic'].append(MODULE+'.sv')
        else: raise ValueError('unexpected changes outside D-cache: '+k)
    return dict(ordered_hdl_sources=len(x),**types)


def generate(kit,out,tool):
    kit=kit.resolve(strict=True)
    subprocess.run(['sha256sum','--quiet','-c','CANDIDATE.sha256'],cwd=kit,check=True)
    if (kit/'sources.f').read_text().splitlines().count('rtl/'+MODULE+'.sv')!=1: raise ValueError('missing or repeated D-cache')
    xml=out/'tree.xml';out.mkdir()
    subprocess.run([tool,'--xml-only','--xml-output',str(xml),'--Mdir',str(out),'-DSYNTHESIS',
                    '--top-module',MODULE,'-Wno-fatal','-F',str(kit/'sources.f')],check=True)
    return Cone(xml)


def run(ref,new,out,tool):
    digest=lambda p:sha256(p.read_bytes()).hexdigest()
    pins=[digest(k/'rtl'/(MODULE+'.sv')) for k in (ref,new)]
    if pins[0]!=STOCK or pins[0]==pins[1]:raise ValueError('wrong reference or unchanged D-cache')
    for k,name in ((ref,'PerfLargeBoom'),(new,'PerfEarlyWayBoom')):
        if (k/'config.scala').read_bytes()!=(Path(__file__).resolve().parents[1]/'rtl/perf'/(name+'.scala')).read_bytes():raise ValueError('wrong model configuration')
    delta=compare_inputs(ref,new); out=out.resolve();out.mkdir(); a,b=[generate(k,out/sub,tool) for k,sub in ((ref,'stock'),(new,'candidate'))]
    result=check_cones(a,b)
    return dict(scope='Generated three-wide RTL, two-state MSHR request way mask after one rising edge on shared S1 inputs. No hypothesis that the mask is one-hot. Not reset initialization, whole-cache equivalence, FPGA timing or a Linux score.',
                parser=subprocess.check_output([tool,'--version'],text=True).strip(),module_sha256=pins,
                kit_seals=[digest(k/'CANDIDATE.sha256') for k in (ref,new)],hdl_comparison=delta,**result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('stock','candidate','out'):p.add_argument(arg,type=Path)
    p.add_argument('--verilator',default='verilator');a=p.parse_args();result=run(a.stock,a.candidate,a.out,a.verilator)
    (a.out/'proof.json').write_text(json.dumps(result,indent=2)+'\n')
