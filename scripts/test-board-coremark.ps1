[CmdletBinding()] param(
 [Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][string]$Capture,[Parameter(Mandatory)][string]$Payload,
 [Parameter(Mandatory)][string]$Elf,[Parameter(Mandatory)][string]$Out,[string]$Bridge=$env:VCU_UART_SERIAL,
 [ValidateSet('baseline','o3','o3-zb','o3-zb-lto','o3-zb-lto-unroll','g15-zb','g15-zb-lto','g15-zb-lto-unroll')][string]$Profile='baseline',
 [ValidatePattern('^[a-f0-9]{16}$')][string]$SessionTag,[switch]$StartSession,
 [ValidateRange(1000,20000)][int]$Iterations=6000)
# Runs the already-installed, profile-specific benchmark on an independently verified live shell.
# Read-only; no configuration, guest downloads, mounts, network or persistent files.
$ErrorActionPreference='Stop'; . (Join-Path $PSScriptRoot board-console.ps1)
if(!$Bridge -or (Test-Path -LiteralPath $Out)){throw 'need exact FPGA-side bridge and new output directory'}
if($StartSession -and !$SessionTag){throw 'missing matrix session tag'}
$prior=Get-Content -Raw -LiteralPath (Join-Path $Capture pass.json)|ConvertFrom-Json
if($prior.test -notin @('linux','linux-dot4','linux-oscheck') -or !$prior.challenge_sent -or $prior.bridge -cne $Bridge){throw 'matching Linux shell required'}
$boot=& python (Join-Path $PSScriptRoot verify-soc-capture.py) $Run $Capture $Payload;if($LASTEXITCODE){throw 'previous Linux boot rejected'}
$port=Find-VcuFpgaUart $Bridge;if($prior.port -ne $port){throw 'serial endpoint changed'}
$elfSha=(Get-FileHash -LiteralPath $Elf).Hash.ToLowerInvariant();$dir=(New-Item -ItemType Directory -Path $Out -ErrorAction Stop).FullName;$nonce=[guid]::NewGuid().ToString('n').Substring(0,14)
[IO.File]::WriteAllText((Join-Path $dir nonce.txt),$nonce);$boot|Set-Content (Join-Path $dir boot.json)
$cmd=& python (Join-Path $PSScriptRoot review-coremark.py) --command --profile $Profile $nonce $Iterations;if($LASTEXITCODE){throw 'cannot generate test command'}
$guest=if($Profile -eq 'baseline'){'/bin/coremark'}else{"/bin/coremark-$Profile"}
$s=[IO.Ports.SerialPort]::new($port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One);$s.Handshake='None';$s.DtrEnable=$false;$s.RtsEnable=$false;$s.WriteTimeout=2000
$all=[Text.StringBuilder]::new();$watch=[Diagnostics.Stopwatch]::StartNew();$t=@{};$deadline=600000
function AwaitLine([string]$line){$pat='(?m)^(?:# )?'+[regex]::Escape($line)+'\r?\n';while($watch.ElapsedMilliseconds -lt $deadline){$chunk=$s.ReadExisting();if($chunk){[void]$all.Append($chunk)};if($all.Length -gt 65536){throw 'unexpected console length'};if($all.ToString() -cmatch "(?m)^(?:# )?CM_(?:performance|validation)_RC_[1-9][0-9]*_${nonce}\r?$" -or $all.ToString() -match 'Kernel panic'){throw 'guest benchmark exited unsuccessfully'};if($all.ToString() -cmatch $pat){return};Start-Sleep -Milliseconds 20};throw 'benchmark timed out'}
try {
 $s.Open();$s.DiscardInBuffer();
 if($StartSession){$s.Write("CMAB=$SessionTag`n")}
 $s.Write(('echo CM_LIVE_$((6*7))_'+$nonce+"`n"));AwaitLine "CM_LIVE_42_$nonce"
 # Also check the expected binary before requesting any benchmark work. Separate from the two-run evidence.
 $s.Write("sha256sum $guest`n");AwaitLine "$elfSha  $guest";[void]$all.Clear()
 $s.Write(('echo CM_LIVE_$((6*7))_'+$nonce+"`n"));AwaitLine "CM_LIVE_42_$nonce"
 if($SessionTag){$s.Write(('echo CM_SESSION_${CMAB}_$((6*7))_'+$nonce+"`n"));AwaitLine "CM_SESSION_${SessionTag}_42_$nonce"}
 if($Profile -like '*-zb*'){
  $s.Write(('cat /proc/cpuinfo; echo CM_ISA_END_$((6*7))_'+$nonce+"`n"));AwaitLine "CM_ISA_END_42_$nonce"
  $isa=[regex]::Matches($all.ToString(),'(?m)^isa\s*:\s*(rv64[a-z0-9_]+)\r?$');if($isa.Count -ne 1){throw 'expected one Linux hart ISA field'}
  $ext=$isa[0].Groups[1].Value.Split('_');if('zba' -notin $ext -or 'zbb' -notin $ext){throw 'Linux has not advertised Zba and Zbb'}
 }
 $s.Write($cmd+"`n")
 foreach($kind in @('performance','validation')) {AwaitLine "CM_${kind}_42_$nonce";$begin=$watch.ElapsedMilliseconds;AwaitLine "CM_${kind}_RC_0_$nonce";$t[$kind]=$watch.ElapsedMilliseconds-$begin}
 AwaitLine "CM_DONE_42_$nonce"
}finally{$s.Dispose();[IO.File]::WriteAllText((Join-Path $dir uart.txt),$all.ToString())}
$t|ConvertTo-Json|Set-Content (Join-Path $dir host-ms.json);$result=& python (Join-Path $PSScriptRoot review-coremark.py) $nonce $Iterations (Join-Path $dir uart.txt) $Elf --profile $Profile --host-ms (Join-Path $dir host-ms.json);if($LASTEXITCODE){throw 'benchmark did not validate'}
$record=$result|ConvertFrom-Json -AsHashtable
$verified=$boot|ConvertFrom-Json
$record['boot']=[ordered]@{utc=$verified.utc;mode=$verified.mode;bit_sha256=$verified.bit_sha256;payload_sha256=$verified.payload_sha256;uart_sha256=$verified.uart_sha256}
$record['iterations_requested']=$Iterations;$record['scope']='One physical VCU118, one RV64GC hart, under Linux; independent measurement, not certified.'
$public=$record|ConvertTo-Json -Depth 8;$public|Set-Content (Join-Path $dir result.json);$public
