$ErrorActionPreference='Stop'; . (Join-Path (Split-Path $PSScriptRoot -Parent) scripts/board-console.ps1)
$n='7fabc'; $start="VCU118_INITRAMFS_READY`r`nSOC_CHECK_PASS bytes=16777216 passes=1 elapsed_s=7`r`n`r`n# "; $echo='echo BOARD_$((40+2))_7fabc'; $bare="VCU118_DIAG_START v1`r`nVCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced`r`n"
$cases=@(
 @('bare',$bare,$false,'PASS'),@('bare',($bare.Split("`n")[1]+"`n"),$false,'WAIT'),@('bare',('ROM4_STOP bad'+$bare),$false,'FAIL'),
 @('linux',$start,$false,'CHALLENGE'),@('linux',($start.TrimEnd('#',' ')),$false,'WAIT'),@('linux',($start+$echo+"`r`n"),$true,'WAIT'),
 @('linux',($start+$echo+"`r`nBOARD_42_other`r`n"),$true,'WAIT'),@('linux',($start+$echo+"`r`nBOARD_42_7fabc`r`n"),$true,'PASS'),
 @('linux',($start+$echo+"`r`nBOARD_42_7fabc`r`nKernel panic"),$true,'FAIL'),@('linux','OpenSBI v1.5',$false,'WAIT'))
foreach($c in $cases){$r=Get-VcuConsoleEvent $c[1] $c[0] $n $c[2]; if($r -ne $c[3]){throw "expected $($c[3]); got $r"}}
Write-Output "HOST_CONSOLE_ACCEPTANCE_PASS cases=$($cases.Count) (no board or serial I/O)"
