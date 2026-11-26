[CmdletBinding()] param([Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][string]$Capture,[Parameter(Mandatory)][string]$Payload,[Parameter(Mandatory)][string]$Out,[string]$Bridge=$env:VCU_UART_SERIAL)
# In the already-booted Linux shell only. No reprogramming, mounts, raw memory or persistent writes.
$ErrorActionPreference='Stop'; . (Join-Path $PSScriptRoot board-console.ps1)
if(!$Bridge -or (Test-Path -LiteralPath $Out)){throw 'need explicit FPGA-side bridge and unused output directory'}
$prior=Get-Content -Raw -LiteralPath (Join-Path $Capture pass.json) | ConvertFrom-Json
if($prior.test -ne 'linux' -or !$prior.challenge_sent -or $prior.bridge -cne $Bridge){throw 'previous matching physical Linux shell capture required'}
$priorPublic=& python (Join-Path $PSScriptRoot verify-soc-capture.py) $Run $Capture $Payload
if($LASTEXITCODE -ne 0){throw 'previous shell evidence rejected'}
$port=Find-VcuFpgaUart $Bridge; if($port -ne $prior.port){throw 'serial endpoint changed since boot'}
[void][IO.Directory]::CreateDirectory($Out); $s=[IO.Ports.SerialPort]::new($port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One); $s.DtrEnable=$false;$s.RtsEnable=$false;$s.Handshake='None';$s.WriteTimeout=2000
$nonce=[guid]::NewGuid().ToString('N').Substring(0,14); $raw=[Text.StringBuilder]::new(); $sent=$false; $ts1=$null; $ts2=$null; $clock=[Diagnostics.Stopwatch]::StartNew()
[IO.File]::WriteAllText((Join-Path $Out 'challenge.txt'),$nonce)
# Fixed commands; only the host-generated hexadecimal nonce is interpolated. Arithmetic is expanded by ash, not by PowerShell.
$command='echo BEGIN_$((20+22))_TOKEN; echo NAME; uname -srm; echo CPU; cat /proc/cpuinfo; echo MEM; head -n 1 /proc/meminfo; echo UP1; cat /proc/uptime; echo IRQ1; cat /proc/interrupts; echo LOAD; /bin/soc-check 15; echo STATUS_$?; echo UP2; cat /proc/uptime; echo IRQ2; cat /proc/interrupts; echo END_$((20+22))_TOKEN'
try {
 $s.Open();$s.DiscardInBuffer();$s.Write(('echo LIVE_$((19+23))_'+$nonce+"`n"));$until=[datetime]::UtcNow.AddSeconds(150)
 while([datetime]::UtcNow -lt $until){
  $v=$s.ReadExisting();if($v){[void]$raw.Append($v);if($raw.Length -gt 65536){throw 'unexpectedly long shell output'};$t=$raw.ToString(); if(!$sent -and $t -match "(?m)^(?:# )?LIVE_42_${nonce}\r?`n"){ $sent=$true;$s.Write($command.Replace('TOKEN',$nonce)+"`n") };
   if($sent -and $null -eq $ts1 -and $t -match "(?m)^IRQ1\r?`n"){$ts1=$clock.ElapsedMilliseconds}
   if($sent -and $null -eq $ts2 -and $t -match "(?m)^IRQ2\r?`n"){$ts2=$clock.ElapsedMilliseconds}
   if($sent -and $t -match "(?m)^END_42_${nonce}\r?`n"){break}}
  Start-Sleep -Milliseconds 35
 }
} finally {$s.Dispose();[IO.File]::WriteAllText((Join-Path $Out console.txt),$raw.ToString())}
if(!$sent){throw 'no live shell response, no workload sent'}
if($null -eq $ts1 -or $null -eq $ts2){throw 'incomplete host timing window'}
$interval=$ts2-$ts1
[IO.File]::WriteAllText((Join-Path $Out host-ms.txt),[string]$interval)
$priorPublic | Set-Content (Join-Path $Out boot-evidence.json); $summary=& python (Join-Path $PSScriptRoot review-linux-profile.py) (Join-Path $Out console.txt) $nonce --host-ms $interval
if($LASTEXITCODE -ne 0){throw 'runtime profile did not pass'}; $summary | Set-Content (Join-Path $Out profile.json); $summary
