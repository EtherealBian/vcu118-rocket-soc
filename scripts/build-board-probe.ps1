[CmdletBinding()] param([Parameter(Mandatory)][string]$Run,[string]$Vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat')
# Fresh self-contained run: freeze sources before calling Vivado, keep its original log and bind the bit to both.
$ErrorActionPreference='Stop'; $root=Split-Path -Parent $PSScriptRoot
$dir=[IO.Path]::GetFullPath($Run,$PWD.Path); if(Test-Path -LiteralPath $dir){throw 'fresh run directory required'}
$snap=Join-Path $dir source; $sources=[ordered]@{}; foreach($rel in @('rtl/boardprobe/probe_protocol.sv','rtl/boardprobe/vcu118_probe.sv','rtl/boardprobe/probe.xdc','scripts/build-board-probe.tcl')){
  $dst=Join-Path $snap $rel; [void][IO.Directory]::CreateDirectory((Split-Path -Parent $dst)); Copy-Item -LiteralPath (Join-Path $root $rel) -Destination $dst; $sources[$rel]=(Get-FileHash -LiteralPath $dst).Hash.ToLowerInvariant()
}
Push-Location -LiteralPath $dir
try {
  & $Vivado -mode batch -nojournal -log vivado.log -source "$snap/scripts/build-board-probe.tcl" -tclargs "$dir/impl" *> console.txt
  if($LASTEXITCODE -ne 0 -or (Select-String -Path vivado.log -Pattern '^(CRITICAL WARNING|ERROR):' -Quiet) -or !(Select-String -Path vivado.log -Pattern '^VCU118_PROBE_BIT_WRITTEN\s*$' -Quiet)){throw "Vivado failed or issued a critical warning: $dir"}
  $bit=(Get-FileHash -LiteralPath impl/probe.bit).Hash.ToLowerInvariant(); $log=(Get-FileHash -LiteralPath vivado.log).Hash.ToLowerInvariant()
  [ordered]@{sources=$sources;bit_sha256=$bit;log_sha256=$log}|ConvertTo-Json|Set-Content build-evidence.json
  & python "$PSScriptRoot/review-board-probe.py" $dir; if($LASTEXITCODE -ne 0){throw 'review rejected build'}
} finally {Pop-Location}
