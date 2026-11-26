[CmdletBinding()] param([ValidateSet('bare','linux')][string]$Mode='bare',[string]$Run,[ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ReviewedBitSha256,[switch]$Program,[ValidateRange(30,1800)][int]$TimeoutSeconds=240,[string]$Vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat',[string]$Cable=$env:VCU_CABLE_SERIAL,[string]$Bridge=$env:VCU_UART_SERIAL,[string]$Slr0Dna=$env:VCU_SLR0_DNA)
# Default preflight never writes to the board. -Program requires prior manual review of CDC/IO/DRC and exact bit SHA.
$ErrorActionPreference='Stop'; . (Join-Path $PSScriptRoot board-console.ps1); $root=Split-Path $PSScriptRoot -Parent
if (!$Bridge -or ($Program -and (!$Cable -or $Slr0Dna -notmatch '^0x[0-9a-fA-F]+$'))) {throw 'Pass -Bridge for preflight; -Program also requires -Cable and -Slr0Dna from local enumeration'}
$port=Find-VcuFpgaUart $Bridge; Write-Output "FPGA_SCI_PORT=$port bridge=$Bridge cable=$Cable"
if (!$Program) {Write-Output 'PREFLIGHT_ONLY_NO_PROGRAM'; return}
if (!$Run -or !$ReviewedBitSha256) {throw '-Program requires -Run and manually reviewed -ReviewedBitSha256'}
$runDir=(Resolve-Path -LiteralPath $Run).Path; $bit=Join-Path $runDir 'obj\VCU118FPGATestHarness.bit'; if (!(Test-Path -LiteralPath $bit -PathType Leaf)) {throw 'missing routed bitstream'}
$logDir=Join-Path $root ('logs\hw-'+$Mode+'-'+[guid]::NewGuid().ToString('N')); [void][IO.Directory]::CreateDirectory($logDir)
$review=& python (Join-Path $PSScriptRoot review-fpga.py) $runDir; if ($LASTEXITCODE -ne 0) {throw 'route/timing evidence rejected; no programming'}; $review|Set-Content "$logDir\implementation.json"; $r=$review -join "`n"|ConvertFrom-Json
if (!$r.route_and_constrained_timing_met -or $r.bit_sha256 -ne $ReviewedBitSha256 -or (Get-FileHash -LiteralPath $bit).Hash -ne $ReviewedBitSha256) {throw 'review or bit hash mismatch'}
$nonce=[guid]::NewGuid().ToString('N').Substring(0,14); $text=''; $armed=$false; $sent=$false; $job=$null; $writer=$null; $accepted=$false; $tool=Join-Path $PSScriptRoot program-test-board.tcl
$sp=[IO.Ports.SerialPort]::new($port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One); $sp.Handshake='None'; $sp.DtrEnable=$false; $sp.RtsEnable=$false; $sp.WriteTimeout=2000
try {
 $sp.Open(); $writer=[IO.StreamWriter]::new("$logDir\uart.txt",$false,[Text.UTF8Encoding]::new($false)); $writer.AutoFlush=$true
 $job=Start-Job -ArgumentList $Vivado,$tool,$bit,$Cable,$Slr0Dna,$logDir -ScriptBlock {param($viv,$t,$b,$c,$dna,$d); Set-Location -LiteralPath $d; & $viv -mode batch -nojournal -log "$d\vivado.log" -source $t -tclargs $b $c xcvu9p_0 $dna "$d\arm" "$d\ack" "$d\programmed" *> "$d\vivado-console.txt"; if($LASTEXITCODE -ne 0){throw "programmer exit $LASTEXITCODE"} }
 $until=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
 while ([DateTime]::UtcNow -lt $until) {
  if ($job.State -in 'Failed','Stopped') {throw "JTAG programming failed; $logDir"}
  if (!$armed -and (Test-Path "$logDir\arm")) {$sp.DiscardInBuffer(); $armed=$true; [IO.File]::WriteAllText("$logDir\ack",'collector ready')}
  if ($armed) {$s=$sp.ReadExisting(); if ($s) {$writer.Write($s); $text+=$s; if ($text.Length -gt 262144){$text=$text.Substring($text.Length-131072)}} }
  # Preserve early boot text, but never send a command to an unidentified pre-existing design.
  if ((Test-Path "$logDir\programmed") -and $job.State -eq 'Completed') {
   $event=Get-VcuConsoleEvent $text $Mode $nonce $sent; if($event -eq 'FAIL'){throw "Guest failure; $logDir"}
   if($event -eq 'CHALLENGE'){$sp.Write('echo BOARD_$((40+2))_'+$nonce+"`n"); $sent=$true}
   if($event -eq 'PASS'){$accepted=$true; break}
  }; Start-Sleep -Milliseconds 30
 }; if(!$accepted){throw "Timeout: not a board PASS. Evidence: $logDir"}
 [ordered]@{test=$Mode;bit_sha256=$ReviewedBitSha256;board_dna=$Slr0Dna;cable=$Cable;bridge=$Bridge;port=$port;challenge_sent=$sent;utc=[datetime]::UtcNow.ToString('o');uart_sha256=(Get-FileHash "$logDir\uart.txt").Hash}|ConvertTo-Json|Set-Content "$logDir\pass.json"
 Write-Output "PHYSICAL_${Mode}_PASS $logDir"
} finally {if($writer){$writer.Dispose()}; $sp.Dispose(); if($job){if($job.State -notin 'Completed','Failed','Stopped'){Stop-Job $job}; Remove-Job $job -Force}}
