$ErrorActionPreference='Stop'; . (Join-Path (Split-Path $PSScriptRoot -Parent) scripts/board-console.ps1)
$n='7fabc'; $start="VCU118_INITRAMFS_READY`r`nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=7`r`n`r`n# "; $echo='echo BOARD_$((40+2))_7fabc'; $bare="VCU118_DIAG_START v1`r`nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced`r`n"
$addr="VCU118_ADDR_START v1`r`nVCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512`r`n"
$cases=@(
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
