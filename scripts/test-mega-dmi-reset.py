#!/usr/bin/env python3
"""Follow the two routed DMI CDC-10 endpoints into the sealed RTL and test reset mid-transaction."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

HERE=Path(__file__).resolve().parent
TB=HERE.parent/'tests/mega_dmi_reset.sv'
KITS=['b028ea3240ec145dd6a91db10bd716c2b630c527da156ea06fd6b840168d5959','ce0ef1171c7b0077282602c5c97230d03850b71c350c6c9ddcdf0b7ebcb5a456']
CDC='b7b4ff7357a3f7f21b5c79a1cc8ed90f21e925c374712f6ade8d7aa767b5c3a6'
JR='_system_debug_systemjtag_reset_catcher_io_sync_reset'; CQ='_debug_reset_syncd_debug_reset_sync_io_q'; JT='_iocell_jtag_TCK_i'; BC='_system_auto_cbus_fixedClockNode_anon_out_clock'; BR=BC[:-5]+'reset'
AS='TLAsyncCrossingSource_a9d32s1k1z2u'; DS='TLAsyncCrossingSink_a9d32s1k1z2u'; QA='AsyncQueueSource_TLBundleA_a9d32s1k1z2u'; QD=QA.replace('BundleA','BundleD'); SY='AsyncResetSynchronizerShiftReg_w1_d3_i0'; OUT='TLDebugModuleOuterAsync'; IN='TLDebugModuleInnerAsync'
A_D='_dmInner_auto_dmiXing_in_a_safe_sink_reset_n'; D_J='_dmOuter_auto_asource_out_d_safe_sink_reset_n'
PINS=[('ChipTop','ResetCatchAndSync_d3','system_debug_systemjtag_reset_catcher',dict(clock=JT,reset=BR,io_sync_reset=JR)),('ChipTop',SY,'debug_reset_syncd_debug_reset_sync',dict(clock=BC,reset=JR,io_d="1'h1",io_q=CQ)),
 ('ChipTop','ResetSynchronizerShiftReg_w1_d3_i0','dmactiveAck_dmactiveAck',dict(clock=BC,reset='~'+CQ,io_d='_system_debug_dmactive',io_q='_dmactiveAck_dmactiveAck_io_q')),
 ('ChipTop','DigitalTop','system',dict(debug_clock=BC,debug_reset='~'+CQ,debug_systemjtag_reset=JR,debug_systemjtag_jtag_TCK=JT,resetctrl_hartIsInReset_0=BR,debug_dmactiveAck='_dmactiveAck_dmactiveAck_io_q')),
 ('DigitalTop','TLDebugModule','tlDM',dict(io_debug_clock='debug_clock',io_debug_reset='debug_reset',io_dmi_dmiClock='debug_systemjtag_jtag_TCK',io_dmi_dmiReset='debug_systemjtag_reset',io_tl_clock='_cbus_auto_fixedClockNode_anon_out_2_clock',io_tl_reset='_cbus_auto_fixedClockNode_anon_out_2_reset',io_hartIsInReset_0='resetctrl_hartIsInReset_0',io_ctrl_dmactiveAck='debug_dmactiveAck')),
 ('TLDebugModule',OUT,'dmOuter',dict(io_dmi_clock='io_dmi_dmiClock',io_dmi_reset='io_dmi_dmiReset',auto_asource_out_a_safe_sink_reset_n=A_D,auto_asource_out_d_safe_sink_reset_n=D_J)),
 ('TLDebugModule',IN,'dmInner',dict(io_debug_clock='io_debug_clock',io_debug_reset='io_debug_reset',auto_dmiXing_in_a_safe_sink_reset_n=A_D,auto_dmiXing_in_d_safe_sink_reset_n=D_J)),
 (OUT,AS,'asource',dict(clock='io_dmi_clock',reset='io_dmi_reset',auto_out_a_safe_sink_reset_n='auto_asource_out_a_safe_sink_reset_n',auto_out_d_safe_sink_reset_n='auto_asource_out_d_safe_sink_reset_n')),
 (IN,DS,'dmiXing',dict(clock='io_debug_clock',reset='io_debug_reset',auto_in_a_safe_sink_reset_n='auto_dmiXing_in_a_safe_sink_reset_n',auto_in_d_safe_sink_reset_n='auto_dmiXing_in_d_safe_sink_reset_n'))]
for layer,unit,inst,interface in [(AS,QA,'nodeOut_a_source','auto_out_a'),(DS,QD,'nodeIn_d_source','auto_in_d'),(AS,QD.replace('Source','Sink'),'nodeIn_d_sink','auto_out_d'),(DS,QA.replace('Source','Sink'),'nodeOut_a_sink','auto_in_a')]:
    PINS.append((layer,unit,inst,dict(clock='clock',reset='reset',io_async_safe_sink_reset_n=interface+'_safe_sink_reset_n')))
for q in (QA,QD): PINS.append((q,'AsyncValidSync','source_valid_0',dict(clock='clock',reset='reset | ~io_async_safe_sink_reset_n',io_in="1'h1")))
for sig in ('clock','reset'):
    for outer,inner,top in [(5,6,'auto_cbus_fixedClockNode_anon_out_'),(2,3,'_cbus_auto_fixedClockNode_anon_out_2_')]:
        PINS.extend([('DigitalTop','PeripheryBus_cbus','cbus',{'auto_fixedClockNode_anon_out_'+str(outer)+'_'+sig:top+sig}),('PeripheryBus_cbus','FixedClockBroadcast_7','fixedClockNode',{'auto_anon_out_'+str(inner)+'_'+sig:'auto_fixedClockNode_anon_out_'+str(outer)+'_'+sig})])
CYCLES=[(10000,73),(16667,131),(12500,311),(20000,991)]


def need(ok,msg):
    if not ok: raise ValueError(msg)


def h(p):return sha256(p.read_bytes()).hexdigest()


def run(stock,kit,cdc,vivado,out):
    need(not out.exists() and all(p not in out.parents and out not in p.parents for p in (kit,stock,vivado)), 'fresh separate output required')
    need([h(k/'CANDIDATE.sha256') for k in (stock,kit)]==KITS and h(cdc)==CDC,'wrong run or archived CDC')
    seals=runpy.run_path(str(HERE/'verify-mega-impl-inputs.py'))['seals']; old,new=seals(stock),seals(kit)
    table=cdc.read_text(); suffix='/source_valid_0/io_out_sink_valid_0/output_chain/sync_2_reg/CLR'; prefix='chiptop0/system/tlDM/'
    reports=[]
    for fr,to,source,leaf in [('clk_out1_harnessSysPLL','JTCK','debug_reset_syncd_debug_reset_sync/output_chain/sync_0_reg/C','dmOuter/asource/nodeOut_a_source'),('JTCK','clk_out1_harnessSysPLL','system_debug_systemjtag_reset_catcher/io_sync_reset_chain/output_chain/sync_0_reg/C','dmInner/dmiXing/nodeIn_d_source')]:
        blocks=re.split(r'(?m)(?=^Source Clock: )',table); matches=[b for b in blocks if b.startswith('Source Clock: '+fr+'\nDestination Clock: '+to+'\n')];need(len(matches)==1,'wrong clock pair')
        src='chiptop0/'+source; dst=prefix+leaf+suffix
        rows=[line for line in matches[0].splitlines() if 'CDC-10  Critical' in line];need(len(rows)==1 and rows[0].split()[-2:]==[src,dst] and '6  Asynch Clock Groups' in rows[0],'incorrect endpoints');reports.append(dict(source_clock=fr,destination_clock=to,source=src,endpoint=dst))
    directory=kit/'rtl'; by_name={p.stem:p for p in directory.iterdir() if p.suffix in ('.v','.sv')}
    def src(n):return re.sub(r'//[^\n]*','',by_name[n].read_text())
    units=set();todo={'TLDebugModule',SY,'ResetCatchAndSync_d3','ResetSynchronizerShiftReg_w1_d3_i0'}
    while todo:
        n=todo.pop();units.add(n);todo|=(set(re.findall(r'\b\w+\b',src(n))) & set(by_name))-units
    need(len(units)==33,'different debug module closure'); names=units|{p[0] for p in PINS}|{'FixedClockBroadcast_7'}; ids={n:new['rtl/'+by_name[n].name] for n in sorted(names)}
    need(all(old['rtl/'+by_name[n].name]==v for n,v in ids.items()),'archived and candidate cones differ')
    for parent,typ,inst,pins in PINS:
        block=re.findall(r'^\s*'+typ+r'\s+'+inst+r'\s*\(\s*\n(.*?)^\s*\);',src(parent),re.M|re.S);need(len(block)==1,'missing instance '+inst)
        for k,v in pins.items():need(re.findall(r'^\s*\.'+k+r'\s*\(([^\n]*)\),?\s*$',block[0],re.M)==[v],'unexpected '+inst+'.'+k)
    for i in (3,6):
        for sig in ('clock','reset'):need(f'assign auto_anon_out_{i}_{sig} = auto_anon_in_{sig};' in src('FixedClockBroadcast_7'),'cbus broadcast')
    for q in (QA,QD):need('assign io_async_safe_sink_reset_n = ~reset;' in src(q.replace('Source','Sink')),'sink reset wiring')
    out.mkdir();records=[]
    def execute(d,name,args,label,fatal=None):
        ext='.bat' if os.name=='nt' else '';proc=subprocess.run([str(vivado/'bin'/(name+ext)),*map(str,args)],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
        text=proc.stdout.decode(errors='replace').replace('\r','');(d/(label+'.txt')).write_bytes(text.encode());
        if fatal: need(re.findall(r'(?m)^Fatal: (.*)$',text)==[fatal] and 'DMI_RESULT' not in text,'wrong injected failure: '+label)
        else: need(proc.returncode==0 and not re.search(r'(?im)^\s*(fatal:|error:)',text),label+' failed; inspect log')
        return text
    for mutant in (False,True):
        d=out/('drop_remote_request_clear' if mutant else 'actual');d.mkdir(); inputs=[by_name[n] for n in sorted(units)];
        if mutant:
            raw=by_name[QA].read_text(); start=raw.index('AsyncValidSync source_valid_0 (');end=raw.index(');',start);frag=raw[start:end];need(frag.count('reset | ~io_async_safe_sink_reset_n')==1,'missing mutation site'); copy=d/by_name[QA].name;copy.write_bytes((raw[:start]+frag.replace('reset | ~io_async_safe_sink_reset_n','reset')+raw[end:]).encode());inputs[inputs.index(by_name[QA])]=copy
        execute(d,'xvlog',['--sv','-d','SYNTHESIS',*inputs,TB],'compile');e=execute(d,'xelab',['tb','--mt','off','--timescale','1ps/1ps','-s','dmi'],'elab');need('Vivado Simulator v2024.2' in e and 'Built simulation snapshot dmi' in e,'wrong simulator')
        def sim(i,stage,ab,extra=None,fatal=None):
            flags=['CASE'+str(i),'PENDING_RSP' if stage else 'PENDING_REQ','ABORT' if ab else 'KEEP']+([extra] if extra else []);return execute(d,'xsim',['dmi',*[x for f in flags for x in ('--testplusarg',f)],'--runall'],'-'.join(flags),fatal)
        if mutant: sim(0,0,1,fatal='QUEUE_CLEAR_CONE');continue
        for i,(hj,ph) in enumerate(CYCLES):
            for stage in (0,1):
                for ab in (0,1):
                    text = sim(i, stage, ab)
                    clocks = re.findall(r'^DMI_CLOCK cpu_half_ps=(\d+) jtck_half_ps=(\d+) jtck_phase_ps=(\d+)$', text, re.M)
                    need(len(clocks) == 1 and tuple(map(int, clocks[0])) == (2857, hj, ph), 'wrong simulated clock case')
                    rows = re.findall(r'^DMI_RESULT stage=(\d) abort=(\d) mid_enqueue=(\d+) inner_a_at_stop=(\d+) inner_d_at_stop=(\d+) final_mid_a=(\d+) mid_response=(\d+) fresh_word=([0-9a-f]+)$', text, re.M)
                    need('$finish called' in text and len(rows) == 1, 'missing or duplicate case completion')
                    actual = tuple(map(int, rows[0][:7]))
                    need(actual == (stage, ab, 1, stage, stage, stage if ab else 1, 1 - ab)
                         and rows[0][7] == '52e4c786', 'unexpected transaction outcome')
                    records.append(dict(jtck_half_ps=int(clocks[0][1]), jtck_phase_ps=int(clocks[0][2]),
                                        stage='response_pending' if stage else 'request_in_crossing', reset=bool(ab),
                                        request_enqueue=actual[2], inner_accept_at_stop=actual[3],
                                        inner_response_at_stop=actual[4], final_inner_accept=actual[5],
                                        external_response=actual[6], fresh_readback=rows[0][7]))
        sim(0,1,1,extra='CORRUPT',fatal='FRESH_DATA0_READBACK')
    return dict(scope='Functional TLDebugModule with actual ChipTop reset/ack chains; CBus clock/reset and public DMI handshake stimulus, no serial TAP, physical clear timing, metastability or board performance.',physical_cdc_report_sha256=CDC,archived_and_candidate_kit_sha256=KITS,archived_endpoints=reports,simulated_rtl_files=len(units),checked_input_sha256=ids,checked_parent_instance_pins=sum(len(p[3]) for p in PINS),fixture_sha256=h(TB),cpu_half_ps=2857,cbus_reset_pulse_ps=800,jtck_edges_before_jtag_release=3,subsequent_cpu_edges_before_debug_release=3,queue_chain_after_joint_deassertion='001,011,111 on the first three local rising edges in reset cases',negative_controls={'missing_remote_request_clear':'QUEUE_CLEAR_CONE','corrupt_fresh_write':'FRESH_DATA0_READBACK'},cases=records)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('stock','kit','cdc','vivado','out'):p.add_argument(n,type=Path)
    a=p.parse_args();r=run(**{n:p.resolve() for n,p in vars(a).items()});(a.out/'result.json').write_bytes((json.dumps(r,indent=2)+'\n').encode());print('DMI_RESET_CASES',len(r['cases']))
