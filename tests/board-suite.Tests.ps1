# Preflight-only: an empty dummy bit is deliberately not a programmable design.
# Each failure must occur before creating an output directory or calling Vivado/serial I/O.
$ErrorActionPreference='Stop';$suite=Join-Path (Split-Path $PSScriptRoot -Parent) scripts/run-board-suite.ps1
$tmp=Join-Path ([IO.Path]::GetTempPath()) ('vcu-suite-test-'+[guid]::NewGuid().ToString('n'));$null=New-Item -ItemType Directory -Path (Join-Path $tmp obj) -Force
try {
 $bit=Join-Path $tmp 'obj/VCU118FPGATestHarness.bit';[IO.File]::WriteAllText($bit,'dummy bit for host preflight only');$hash=(Get-FileHash $bit).Hash
 $out=Join-Path $tmp never-created
 $a=@{Program=$true;Run=$tmp;ReviewedBitSha256=$hash;Out=$out;Payloads=@{};Modes=@('bare');Bridge='fixture';Cable='fixture';Slr0Dna='0x11';Vivado='never-invoke-vivado'}
 function Reject($override,$reason){$b=$a.Clone();foreach($k in $override.Keys){$b[$k]=$override[$k]};$why=$null;try {& $suite @b}catch{$why=$_.Exception.Message};if(!$why -or $why -notlike "*$reason*" -or (Test-Path -LiteralPath $out)){throw "unexpected result for $reason : $why"}}
 Reject @{Modes=@('bare','bare')} 'duplicate modes'; Reject @{Modes=@('linux');ReadMigAfterBare=$true} 'MIG without';Reject @{ReviewedBitSha256=('1'*64)} 'differs from reviewed';Reject @{} 'missing payload for bare';Reject @{Program=$false} 'explicit target';Reject @{Slr0Dna='wrong'} 'explicit target';Reject @{Payloads=@{bare=$bit};Modes=@('bare','linux')} 'missing payload for linux'
 Write-Output 'BOARD_SUITE_PREFLIGHT_NEGATIVES_PASS cases=7 (no hardware)'
} finally {if(Test-Path -LiteralPath $bit){Remove-Item -LiteralPath $bit};Remove-Item -LiteralPath (Join-Path $tmp obj);Remove-Item -LiteralPath $tmp}
