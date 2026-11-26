[CmdletBinding()] param([string]$Vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat', [string]$Distro='Ubuntu-20.04')
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent
$linuxRoot=(& wsl.exe -d $Distro -- wslpath -u ($root.Replace('\','/')) | Select-Object -First 1).Trim(); if($LASTEXITCODE -or -not $linuxRoot){throw 'WSL path conversion failed'}
$run=Join-Path $root ('artifacts\fpga-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,6)); [void][IO.Directory]::CreateDirectory($run)
& wsl.exe -d $Distro -- bash "$linuxRoot/scripts/generate-rtl.sh" *> "$run\generate.log"; if($LASTEXITCODE){throw "RTL generation failed: $run\generate.log"}
$m=Select-String -LiteralPath "$run\generate.log" -Pattern '^MANIFEST_READY=(.+)$' | Select-Object -Last 1; if(!$m){throw 'No FPGA source manifest marker'}
$mf=(& wsl.exe -d $Distro -- wslpath -w $m.Matches[0].Groups[1].Value.Trim()).Trim(); if(!(Test-Path -LiteralPath $mf -PathType Leaf)){throw 'missing RTL file manifest'}
$up=Join-Path $root 'third_party\chipyard\fpga\fpga-shells\xilinx\common\tcl'; $t=Join-Path $PSScriptRoot 'implement.tcl'
& $Vivado -mode batch -notrace -nojournal -log "$run\vivado.log" -source $t -tclargs $mf $up $run; if($LASTEXITCODE){throw "implementation failed: $run\vivado.log"}
if(!(Select-String -SimpleMatch 'BIT_WRITTEN_SETUP_HOLD_NONNEGATIVE_REVIEW_CDC_AND_COVERAGE' -LiteralPath "$run\vivado.log")){throw 'no completion marker'}
Get-FileHash (Join-Path $run 'obj\VCU118FPGATestHarness.bit'); Write-Output "Review coverage and CDC reports in $run before signoff."
