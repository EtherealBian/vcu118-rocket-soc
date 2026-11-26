[CmdletBinding()]param([string]$VivadoBin='D:\Xilinx\Vivado\2024.2\bin')
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent
$run=Join-Path $root ('artifacts\accel-sim-'+[Guid]::NewGuid().ToString('N').Substring(0,8)); [void][IO.Directory]::CreateDirectory($run)
Push-Location $run; try {
 & "$VivadoBin\xvlog.bat" --sv "$root\rtl\accel\dot4_i8.sv" "$root\tests\tb_dot4_i8.sv"; if($LASTEXITCODE){throw 'xvlog failed'}
 & "$VivadoBin\xelab.bat" tb_dot4_i8 -s dot_test; if($LASTEXITCODE){throw 'xelab failed'}
 & "$VivadoBin\xsim.bat" dot_test -runall -log sim.txt; if($LASTEXITCODE -or !(Select-String -Quiet -Path sim.txt -Pattern '^DOT4_SIM_PASS ')){throw 'RTL self-check failed'}
 Get-Content sim.txt | Select-String '^DOT4_SIM_PASS'; Write-Output "SIM_EVIDENCE=$run"
} finally {Pop-Location}
