#!/usr/bin/env python3
"""Build and formally check the common registered F3 physical experiment boundary."""
import argparse
import json
import runpy
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

F = runpy.run_path(str(Path(__file__).with_name('test-mega-f3-history-compare.py')))
I, O = F['INPUT'], F['OUTPUT']
PROOF = '3be98711cc7cf35eaec7e6ea053a864b63f9e381706212ccc5b0a17dbf115deb'
PARENT = '2ac05989d4a0ffb90e21487f7a4e671e9f3f20ad2836d805faa41d6f817d7aa0'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return sha256(data).hexdigest()


def layout(ports):
    low = 0
    for name, width in ports.items():
        yield name, low, low + width - 1
        low += width


def width(n):
    return ('[%d:0] ' % (n-1)) if n > 1 else ''


def boundary():
    pins = ['.%s(launch[%d:%d])' % (n, h, l) for n, l, h in layout(I)]
    pins += ['.o%d(raw[%d:%d])' % (i, h, l) for i, (_, l, h) in enumerate(layout(O))]
    return '''module f3_boundary(input clock, input [555:0] stimulus, output [81:0] observed);
(* DONT_TOUCH="yes" *) reg [555:0] launch;
(* DONT_TOUCH="yes" *) reg [81:0] capture;
wire [81:0] raw;
top dut(\n'''+',\n'.join(pins)+''');
always @(posedge clock) begin
  launch <= stimulus;
  capture <= raw;
end
assign observed = capture;
endmodule
'''


def oracle():
    # No bit slices or offsets from the DUT generator. Named *external* ports,
    # stock equations before the reference delay, reversed Verilog concatenations.
    outputs = list(O)
    decl = ['input '+width(w)+n for n, w in I.items()]
    text = ['module compare(input clock, output differs, '+', '.join(decl)+');',
            'wire [81:0] actual;', 'f3_boundary uut(clock, {'+', '.join(reversed(I))+'}, actual);']
    text += ['wire '+width(w)+'ref'+str(i)+';' for i, w in enumerate(O.values())]
    pins = ['.'+n+'('+n+')' for n in I] + [f'.o{i}(ref{i})' for i in range(len(outputs))]
    text += ['stock_oracle ref_dut('+', '.join(pins)+');', 'reg [81:0] first, second;',
             'always @(posedge clock) begin first <= {'+', '.join('ref'+str(i) for i in reversed(range(len(outputs))))+'}; second <= first; end',
             'assign differs = |(actual ^ second);', 'endmodule']
    return '\n'.join(text)+'\n'


def write(path, text):
    path.write_bytes(text.encode())


def influence(out, yosys):
    # An actual dependence requires a physical path; the converse need not hold.
    # Prove or disprove bit independence with every other named input arbitrary.
    rows=[]
    for lane, pred in enumerate(F['PRED']):
        decl=['input '+width(w)+n for n,w in I.items() if n!=pred]
        body=['module influence(output [81:0] d, '+', '.join(decl)+');']
        for forced in (0,1):
            pins=['.'+n+'('+('1\'b'+str(forced) if n==pred else n)+')' for n in I]
            outs=[]
            for i,w in enumerate(O.values()):
                net=f'b{forced}_{i}'; body.append('wire '+width(w)+net+';');outs.append(net);pins.append(f'.o{i}({net})')
            body+=['top u'+str(forced)+'('+', '.join(pins)+');','wire [81:0] v'+str(forced)+' = {'+', '.join(reversed(outs))+'};']
        body+=['assign d = v0 ^ v1;', 'endmodule']
        name=f'lane-{lane}'; write(out/(name+'.v'),'\n'.join(body)+'\n')
        queries=[f'sat -prove d[{bit}] 0 -show d[{bit}] influence' for bit in range(82)]
        cmds=f'read_verilog -noautowire stock.v {name}.v\nhierarchy -check -top influence\nproc; flatten; opt; check -assert\n'+'\n'.join(queries)+'\n'
        write(out/(name+'.ys'),cmds)
        with (out/(name+'.log')).open('wb') as stream:
            subprocess.run([str(yosys),'-Q','-T','-s',name+'.ys'],cwd=out,stdout=stream,stderr=subprocess.STDOUT,timeout=180,check=True)
        log=(out/(name+'.log')).read_text().split('Executing SAT pass')[1:]
        need(len(log)==82, 'missing bit-level SAT query')
        required=[]
        for bit, query in enumerate(log):
            good=query.count('SAT proof finished - no model found: SUCCESS!'); bad=query.count('SAT proof finished - model found: FAIL!')
            need(good+bad==1 and query.count(f"Import proof-constraint: \\d [{bit}] = 1'0")==1, 'incomplete or wrong bit decision')
            if bad: required.append(bit)
        rows.append(required)
    return rows


def run(kit, proofdir, parent, out, yosys):
    need(not out.exists() and not any(d==out or d in out.parents for d in (kit, proofdir)), 'requires fresh separate directory')
    seal = (kit/'CANDIDATE.sha256').read_bytes(); raw = (kit/'rtl/BoomFrontend.sv').read_bytes()
    proof = (proofdir/'result.json').read_bytes(); pr = json.loads(proof); pa = parent.read_bytes()
    need(sha(raw)==F['LEAF'] and sha(seal)==F['SEAL'] and (F['LEAF']+'  rtl/BoomFrontend.sv').encode() in seal.splitlines(), 'unrecognized implementation input')
    need(sha(proof)==PROOF and sha(pa)==PARENT and json.loads(pa)['proof_sha256']==PROOF, 'different qualification records')
    need(sha(yosys.read_bytes())==pr['yosys_sha256'] and subprocess.check_output([str(yosys), '-V'], text=True).strip()==pr['yosys'], 'different proof tool')
    need(sum(I.values())==556 and sum(O.values())==82 and list(I)[:8]==F['PRED'] and all(I[n]==1 for n in F['PRED']), 'different interface')
    src=raw.decode(); p=F['prefix'](src); cuts={}; hashes={}
    for name, leaf in [('stock',src), ('prefix_and_compare',F['derive'](p)), ('eligible_lanes',F['eligible_lanes'](p))]:
        cut=F['extract'](leaf); h=sha(cut.encode()); hashes[name]=h
        need(cut.encode()==(proofdir/(name+'.v')).read_bytes() and h==pr['cut_sha256'][name], 'cut identity mismatch: '+name)
        if name!='stock':
            need(pr['proofs'][name]=='equivalent' and pr['derived_leaf_sha256'][name]==sha(leaf.encode()), 'different candidate')
        cuts[name]=cut
    out.mkdir(); wrap=boundary(); write(out/'boundary.v',wrap); write(out/'clock.xdc','create_clock -name cpu -period 5.714 [get_ports clock]\n')
    for name, cut in cuts.items(): write(out/(name+'.v'),cut)
    write(out/'stock_oracle.v',F['one'](cuts['stock'],'module top(','module stock_oracle(')); write(out/'compare.v',oracle())
    def swap(text, a, b): return F['one'](F['one'](F['one'](text,a,'__TEMP__'),b,a),'__TEMP__',b)
    mutants={'swap_pred0_pred7':swap(wrap, 'launch[0:0]', 'launch[7:7]'), 'swap_f1_f2_results':swap(wrap, 'raw[0:0]', 'raw[1:1]'),
             'bypass_capture':F['one'](wrap,'observed = capture','observed = raw')}
    decisions={}
    for case in [*cuts,*mutants]:
        mutant=case in mutants
        if mutant: write(out/(case+'-boundary.v'),mutants[case])
        top=case+'-boundary.v' if mutant else 'boundary.v'; cut='stock' if mutant else case
        # At step 3 both pipelines have received two arbitrary transactions.
        # No reset, initialization constraints or restrictions on changing inputs.
        cmds=f'read_verilog -noautowire {cut}.v {top} stock_oracle.v compare.v\nhierarchy -check -top compare\nproc; flatten; opt; check -assert\nsat -seq 3 -prove-skip 2 -prove differs 0 -show differs compare\n'
        write(out/(case+'.ys'),cmds)
        with (out/(case+'.log')).open('wb') as stream:
            subprocess.run([str(yosys),'-Q','-T','-s',case+'.ys'],cwd=out,stdout=stream,stderr=subprocess.STDOUT,timeout=180,check=True)
        log=(out/(case+'.log')).read_text(); good='SAT proof finished - no model found: SUCCESS!'; bad='SAT proof finished - model found: FAIL!'
        need((log.count(good),log.count(bad))==((0,1) if mutant else (1,0)), 'unexpected registered comparison: '+case)
        decisions[case]='counterexample' if mutant else 'equivalent_after_two_edges'
    required=influence(out,yosys)
    write(out/'required.tsv','lane\tcapture\tdependent\n'+''.join(f'{lane}\t{bit}\t{int(bit in bits)}\n' for lane,bits in enumerate(required) for bit in range(82)))
    result=dict(scope='Unconstrained binary inputs at each step, stock named-port equations delayed two active edges vs registered packed cuts. Not routed timing, additional SoC stages or board performance.',kit_sha256=F['SEAL'],stock_leaf_sha256=F['LEAF'],proof_sha256=PROOF,parent_sha256=PARENT,yosys_sha256=pr['yosys_sha256'],cut_sha256=hashes,boundary_sha256=sha(wrap.encode()),oracle_sha256=sha(oracle().encode()),clock_xdc_sha256=sha((out/'clock.xdc').read_bytes()),predicted_lane_to_capture_dependent_bits=required,required_tsv_sha256=sha((out/'required.tsv').read_bytes()),steps=3,decisions=decisions,input_lsb_msb=list(layout(I)),output_lsb_msb=list(layout(O)))
    write(out/'result.json',json.dumps(result,indent=2)+'\n');print(json.dumps(decisions))


def check_prepared(folder):
    # This is the pinned public qualification output, not a self-attestation.
    raw=(folder/'result.json').read_bytes()
    need(sha(raw)=='eb88490e2c6be8dce5021294afc5e96798aa4b6a36dd5e964f7ec0bce2eabdd6', 'unrecognized registered qualification')
    r=json.loads(raw); files={n+'.v':h for n,h in r['cut_sha256'].items()}
    files.update({'boundary.v':r['boundary_sha256'],'clock.xdc':r['clock_xdc_sha256'],'required.tsv':r['required_tsv_sha256']})
    for name,h in files.items(): need(sha((folder/name).read_bytes())==h, 'prepared file mismatch: '+name)
    print('F3_REGISTERED_INPUTS_VERIFIED')


if __name__=='__main__':
    if sys.argv[1:2]==['--check-prepared'] and len(sys.argv)==3:
        check_prepared(Path(sys.argv[2]));sys.exit(0)
    a=argparse.ArgumentParser(description=__doc__)
    for n in ('kit','proofdir','parent','out','yosys'): a.add_argument(n,type=Path)
    ns=a.parse_args();run(**{n:p.resolve() for n,p in vars(ns).items()})
