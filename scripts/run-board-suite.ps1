[CmdletBinding()] param(
 [Parameter(Mandatory)][switch]$Program,
 [Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ReviewedBitSha256,
 [Parameter(Mandatory)][string]$Out,[Parameter(Mandatory)][System.Collections.IDictionary]$Payloads,
 [Parameter(Mandatory)][ValidateSet('bare','address','sweep','counters','dot4','dotbench','linux','linux-dot4','linux-oscheck')][string[]]$Modes,
 [switch]$ReadMigAfterBare,[string]$Vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat',
 [string]$Bridge=$env:VCU_UART_SERIAL,[string]$Cable=$env:VCU_CABLE_SERIAL,[string]$Slr0Dna=$env:VCU_SLR0_DNA)
# Runs only on an already reviewed image. Every mode gets its own volatile configuration.
# No parallel UART owners; no flash/SD operations. Stop on the first failed test.
$ErrorActionPreference='Stop'
if(!$Program -or !$Bridge -or !$Cable -or $Slr0Dna -notmatch '^0x[0-9a-fA-F]+$' -or (Test-Path -LiteralPath $Out)){throw 'explicit target, -Program and a new output directory are required'}
if(@($Modes|Sort-Object -Unique).Count -ne $Modes.Count -or ($ReadMigAfterBare -and 'bare' -notin $Modes)){throw 'duplicate modes or MIG without a bare test'}
$runDir=(Resolve-Path -LiteralPath $Run).Path; $bit=Join-Path $runDir 'obj/VCU118FPGATestHarness.bit'
if((Get-FileHash -LiteralPath $bit).Hash -ne $ReviewedBitSha256){throw 'image differs from reviewed hash'}
$files=@{};foreach($m in $Modes){if(!$Payloads.Contains($m)){throw "missing payload for $m"};$files[$m]=(Get-Item -LiteralPath $Payloads[$m] -ErrorAction Stop).FullName;if(!(Test-Path -LiteralPath $files[$m] -PathType Leaf)){throw 'not a payload file'}}
$outDir=(New-Item -ItemType Directory -Path $Out -ErrorAction Stop).FullName
$target=@{Program=$true;Run=$runDir;ReviewedBitSha256=$ReviewedBitSha256;Bridge=$Bridge;Cable=$Cable;Slr0Dna=$Slr0Dna;Vivado=$Vivado}
foreach($m in $Modes){
 $rows=@(& (Join-Path $PSScriptRoot test-connected-board.ps1) @target -Mode $m -UartPayload $files[$m] -TimeoutSeconds 1500)
 $passes=@($rows|Where-Object {$_ -is [string] -and $_.StartsWith("PHYSICAL_${m}_PASS ")})
 if($passes.Count -ne 1){throw "missing or ambiguous $m result"}
 $cap=$passes[0].Substring("PHYSICAL_${m}_PASS ".Length)
 $cert=& python (Join-Path $PSScriptRoot verify-soc-capture.py) $runDir $cap $files[$m];if($LASTEXITCODE){throw "offline capture rejected: $m"}
 $c=$cert -join "`n"|ConvertFrom-Json;if($c.mode -ne $m -or $c.bit_sha256 -ne $ReviewedBitSha256){throw 'capture from another test'}
 $cert|Set-Content -LiteralPath (Join-Path $outDir "$m.json"); Write-Output "REVIEWED_BOARD_TEST $m"
 if($ReadMigAfterBare -and $m -eq 'bare'){
  $mig=Join-Path $outDir 'mig-private';Push-Location -LiteralPath $outDir
  try {& $Vivado -mode batch -nojournal -log (Join-Path $outDir mig.log) -source (Join-Path $PSScriptRoot read-board-mig.tcl) -tclargs $Cable xcvu9p_0 $Slr0Dna present $mig *> (Join-Path $outDir mig-console.txt);if($LASTEXITCODE){throw 'live read-only MIG check failed'}}finally{Pop-Location}
  $v=& python (Join-Path $PSScriptRoot review-live-mig.py) $mig;if($LASTEXITCODE){throw 'MIG report rejected'};$v|Set-Content -LiteralPath (Join-Path $outDir mig.json);Write-Output 'REVIEWED_BOARD_MIG'
 }
}
[IO.File]::WriteAllText((Join-Path $outDir suite.ok),($Modes -join "`n")+"`n");Write-Output "REVIEWED_BOARD_SUITE_PASS $outDir"
