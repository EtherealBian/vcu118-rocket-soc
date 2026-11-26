[CmdletBinding()]param([Parameter(Mandatory)][string]$Run,[string]$VivadoRoot='D:\Xilinx\Vivado\2024.2')
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent; $dir=[IO.Path]::GetFullPath($Run,$PWD.Path); if(Test-Path $dir){throw 'fresh simulation directory required'}
[void][IO.Directory]::CreateDirectory($dir); Push-Location $dir
try{
  $bin=Join-Path $VivadoRoot bin
  & "$bin/xvlog.bat" --sv "$root/rtl/boardprobe/probe_protocol.sv" "$root/rtl/boardprobe/vcu118_probe.sv" "$root/tests/tb_probe_protocol.sv" "$root/tests/tb_probe_clock.sv" "$VivadoRoot/data/verilog/src/glbl.v"; if($LASTEXITCODE){throw 'xvlog failed'}
  foreach($row in @(@('tb_probe_protocol','VCU118_PROBE_PROTOCOL_SIM_PASS'),@('tb_probe_clock','VCU118_PROBE_UNISIM_PASS'))){
    $top=$row[0]; & "$bin/xelab.bat" -mt 2 -L unisims_ver -L secureip $top glbl -s $top; if($LASTEXITCODE){throw 'xelab failed'}
    & "$bin/xsim.bat" $top -runall -log "$top.txt"; if($LASTEXITCODE -ne 0 -or !(Select-String -Path "$top.txt" -SimpleMatch $row[1] -Quiet)){throw "simulation did not pass: $top"}
  }
}finally{Pop-Location}
