$ErrorActionPreference='Stop'; . (Join-Path (Split-Path $PSScriptRoot -Parent) scripts/board-console.ps1)
$n='7fabc'; $start="VCU118_INITRAMFS_READY`r`nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=7`r`n`r`n# "; $echo='echo BOARD_$((40+2))_7fabc'; $bare="VCU118_DIAG_START v1`r`nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced`r`n"
$addr="VCU118_ADDR_START v1`r`nVCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512`r`n"
$dot="DOT4_MMIO_START`r`nDOT4_MMIO_PASS vectors=257 protocol_errors_checked=2`r`n"; $dev='LINUX_DOT4_PASS vectors=257 reserved_rejected=1';$linuxDot=$start.Replace('# ',"$dev`r`n# ")
$counter="VCU118_COUNTER_START v1 n=131072`r`nVCU118_COUNTER_PASS kernels=3 rounds=3`r`n"
$sweep="VCU118_SWEEP_START v1 block_mib=8 blocks=254`r`nVCU118_SWEEP_PASS bytes=2130706432 passes=2`r`n"
$osmark='LINUX_OSCHECK_PASS rounds=64 processes=2 cow_bytes=4096 shared_amoadds=128 fp=s,d';$linuxOs=$start.Replace('# ',"$osmark`r`n# ")
$bench="DOTBENCH_START v1 vectors=257`r`nDOTBENCH_PASS vectors=257 rounds=4`r`n"
$cases=@(
 @('dotbench',$bench,$false,'PASS'),@('dotbench',$bench.Replace('rounds=4','rounds=3'),$false,'WAIT'),@('dotbench',$bench.Replace('DOTBENCH_START','echo DOTBENCH_START'),$false,'WAIT'),@('dotbench',($bench+'DOTBENCH_FAIL'),$false,'FAIL'),
 @('linux-oscheck',$linuxOs,$false,'CHALLENGE'),@('linux-oscheck',$start,$false,'WAIT'),@('linux-oscheck',$linuxOs.Replace('128 fp','127 fp'),$false,'WAIT'),@('linux-oscheck',$linuxOs.Replace($osmark,'LINUX_OSCHECK_FAILED'),$false,'FAIL'),
 @('counters',$counter,$false,'PASS'),@('counters',$counter.Replace('131072','130000'),$false,'WAIT'),@('counters',($counter+'VCU118_COUNTER_FAIL check'),$false,'FAIL'),
 @('sweep',$sweep,$false,'PASS'),@('sweep',$sweep.Replace('2130706432','2147483648'),$false,'WAIT'),@('sweep',($sweep+'VCU118_SWEEP_FAIL data'),$false,'FAIL'),
 @('dot4',$dot,$false,'PASS'),@('dot4',$dot.Replace('257','256'),$false,'WAIT'),@('dot4',$dot.Replace('DOT4_MMIO_START','noise'),$false,'WAIT'),
 @('linux-dot4',$start,$false,'WAIT'),@('linux-dot4',$linuxDot,$false,'CHALLENGE'),@('linux-dot4',$linuxDot.Replace($dev,'LINUX_DOT4_NO_PLATFORM_DEVICE'),$false,'FAIL'),
 @('address',$addr,$false,'PASS'),@('address',$addr.Replace('512','256'),$false,'WAIT'),@('address',$addr.Replace('v1','v2'),$false,'WAIT'),
 @('address',($addr+'VCU118_ADDR_FAIL data'),$false,'FAIL'),@('address',$bare,$false,'WAIT'),@('bare',$addr,$false,'WAIT'),
 @('bare',$bare,$false,'PASS'),@('bare',($bare.Split("`n")[1]+"`n"),$false,'WAIT'),@('bare',('ROM4_STOP bad'+$bare),$false,'FAIL'),
 @('linux',$start,$false,'CHALLENGE'),@('linux',($start.TrimEnd('#',' ')),$false,'WAIT'),@('linux',($start+$echo+"`r`n"),$true,'WAIT'),
 @('linux',($start+$echo+"`r`nBOARD_42_other`r`n"),$true,'WAIT'),@('linux',($start+$echo+"`r`nBOARD_42_7fabc`r`n"),$true,'PASS'),
 @('linux',($start+$echo+"`r`nBOARD_42_7fabc`r`nKernel panic"),$true,'FAIL'),@('linux','OpenSBI v1.5',$false,'WAIT'),
 @('linux',$start.Replace('16777216','167772160'),$false,'WAIT'),@('linux',$start.Replace('passes=1','passes=0'),$false,'WAIT'))
foreach($c in $cases){$r=Get-VcuConsoleEvent $c[1] $c[0] $n $c[2]; if($r -ne $c[3]){throw "expected $($c[3]); got $r"}}
Write-Output "HOST_CONSOLE_ACCEPTANCE_PASS cases=$($cases.Count) (no board or serial I/O)"

if ($null -ne (Get-VcuPostHandoffText ($bare+"UART5_HANDOFF`r"))) {throw 'incomplete handoff accepted'}
if ($null -ne (Get-VcuPostHandoffText "NOT_UART5_HANDOFF`n")) {throw 'substring handoff accepted'}
$remaining=Get-VcuPostHandoffText ($bare+"UART5_HANDOFF`r`n")
if ($null -eq $remaining -or (Get-VcuConsoleEvent $remaining 'bare' $n $false) -ne 'WAIT') {throw 'pre-handoff guest markers counted'}
$remaining=Get-VcuPostHandoffText ("loader`nUART5_HANDOFF`r`n"+$bare)
if ($remaining -cne $bare -or (Get-VcuConsoleEvent $remaining 'bare' $n $false) -ne 'PASS') {throw 'coalesced guest lines lost'}
Write-Output 'HOST_HANDOFF_BOUNDARY_PASS cases=4 (no board or serial I/O)'
