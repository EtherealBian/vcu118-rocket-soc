[CmdletBinding()] param([Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][string]$Capture,[Parameter(Mandatory)][string]$Payload,[Parameter(Mandatory)][string]$Out,[string]$Bridge=$env:VCU_UART_SERIAL)
# Test the already booted Linux TTY via fixed shell commands and hex data only. No configuration or guest files.
$ErrorActionPreference='Stop'; . (Join-Path $PSScriptRoot board-console.ps1)
if(!$Bridge -or (Test-Path -LiteralPath $Out)){throw 'need exact FPGA-side bridge and new output directory'}
$prior=Get-Content -Raw -LiteralPath (Join-Path $Capture pass.json)|ConvertFrom-Json
if($prior.test -notin @('linux','linux-oscheck','linux-dot4') -or !$prior.challenge_sent -or $prior.bridge -cne $Bridge){throw 'expected a matching previously verified Linux boot'}
$boot=& python (Join-Path $PSScriptRoot verify-soc-capture.py) $Run $Capture $Payload;if($LASTEXITCODE){throw 'previous Linux boot rejected'}
$port=Find-VcuFpgaUart $Bridge;if($prior.port -ne $port){throw 'serial endpoint changed'}
$dir=(New-Item -ItemType Directory -Path $Out -ErrorAction Stop).FullName;$nonce=[guid]::NewGuid().ToString('n').Substring(0,14)
$vec=@(for($i=0;$i -lt 32;$i++){[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(128)).ToLowerInvariant()})
[IO.File]::WriteAllText((Join-Path $dir nonce.txt),$nonce);[IO.File]::WriteAllLines((Join-Path $dir vectors.txt),[string[]]$vec);$boot|Set-Content (Join-Path $dir boot.json)
$cmd=& python (Join-Path $PSScriptRoot review-linux-serial.py) --command $nonce;if($LASTEXITCODE){throw 'unable to prepare guest transaction'}
$s=[IO.Ports.SerialPort]::new($port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One);$s.Handshake='None';$s.DtrEnable=$false;$s.RtsEnable=$false;$s.WriteTimeout=2000;$all=[Text.StringBuilder]::new();$watch=[Diagnostics.Stopwatch]::StartNew();$limit=120000
function AwaitLine([string]$line){$pat='(?m)^(?:# )?'+[regex]::Escape($line)+'\r?\n';while($watch.ElapsedMilliseconds -lt $limit){$chunk=$s.ReadExisting();if($chunk){[void]$all.Append($chunk)};if($all.Length -gt 65536){throw 'unexpected console length'};if($all.ToString() -cmatch $pat){return};Start-Sleep -Milliseconds 10};throw 'TTY check timed out'}
try{$s.Open();$s.DiscardInBuffer();$s.Write(('echo LINK_LIVE_$((7*6))_'+$nonce+"`n"));AwaitLine "LINK_LIVE_42_$nonce";$s.Write($cmd+"`n");AwaitLine "LINK_READY_$nonce";for($i=0;$i -lt $vec.Count;$i++){$s.Write($vec[$i]+"`n");AwaitLine "LINK_ACK_$($i+1)_$nonce"};AwaitLine "LINK_END_42_$nonce"}finally{$s.Dispose();[IO.File]::WriteAllText((Join-Path $dir uart.txt),$all.ToString())}
$result=& python (Join-Path $PSScriptRoot review-linux-serial.py) $dir;if($LASTEXITCODE){throw 'independent TTY review rejected capture'};$result|Set-Content (Join-Path $dir result.json);$result
