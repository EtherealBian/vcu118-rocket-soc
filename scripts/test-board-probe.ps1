[CmdletBinding()]
param([Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ReviewedBitSha256,
      [Parameter(Mandatory)][string]$Bridge,[Parameter(Mandatory)][string]$Cable,[Parameter(Mandatory)][ValidatePattern('^0x[0-9a-fA-F]+$')][string]$Slr0Dna,
      [ValidateRange(8,4096)][int]$Count=260,[string]$Vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat')
# Volatile programming only; there is no Flash/SD access in this design or script.
$ErrorActionPreference='Stop'; . "$PSScriptRoot/board-console.ps1"; $root=Split-Path -Parent $PSScriptRoot
$runDir=(Resolve-Path -LiteralPath $Run).Path; $bit=Join-Path $runDir 'impl/probe.bit'
$report=& python "$PSScriptRoot/review-board-probe.py" $runDir; if($LASTEXITCODE -ne 0){throw 'diagnostic implementation rejected'}
$r=$report -join "`n"|ConvertFrom-Json; if($r.design -ne 'vcu118_probe' -or $r.bit_sha256 -ne $ReviewedBitSha256 -or (Get-FileHash $bit).Hash -ne $ReviewedBitSha256){throw 'bit hash or review mismatch'}
$d=Join-Path $root ('logs/probe-hw-'+[guid]::NewGuid().ToString('N')); [void][IO.Directory]::CreateDirectory($d); $report|Set-Content "$d/review.json"
$port=Find-VcuFpgaUart $Bridge; $sp=[IO.Ports.SerialPort]::new($port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One); $sp.Handshake='None'; $sp.DtrEnable=$false; $sp.RtsEnable=$false; $sp.ReadTimeout=1500; $sp.WriteTimeout=1000
$job=$null; $writer=$null; $tool=Join-Path $PSScriptRoot program-test-board.tcl
try {
    $sp.Open(); $job=Start-Job -ArgumentList $Vivado,$tool,$bit,$Cable,$Slr0Dna,$d -ScriptBlock {
        param($v,$t,$b,$c,$dna,$dir); Set-Location -LiteralPath $dir
        & $v -mode batch -nojournal -log "$dir/vivado.log" -source $t -tclargs $b $c xcvu9p_0 $dna "$dir/arm" "$dir/ack" "$dir/programmed" *> "$dir/program.txt"
        if($LASTEXITCODE -ne 0){throw "programmer exit $LASTEXITCODE"}
    }
    $end=[datetime]::UtcNow.AddMinutes(3); $armed=$false
    while($job.State -notin 'Completed','Failed','Stopped'){
        if([datetime]::UtcNow -gt $end){throw 'programmer timed out'}
        if(!$armed -and (Test-Path "$d/arm")){$sp.DiscardInBuffer(); [IO.File]::WriteAllText("$d/ack",'ready'); $armed=$true}; Start-Sleep -Milliseconds 75
    }
    if(!$armed -or $job.State -ne 'Completed' -or !(Test-Path "$d/programmed") -or !(Select-String -SimpleMatch VOLATILE_PROGRAM_AND_READBACK_PASS -Quiet -Path "$d/program.txt")){throw "configuration/readback failed: $d"}
    Start-Sleep -Milliseconds 200; $sp.DiscardInBuffer(); $writer=[IO.StreamWriter]::new("$d/challenges.csv",$false,[Text.UTF8Encoding]::new($false)); $writer.AutoFlush=$true; $writer.WriteLine('index,request,response')
    $random=[Security.Cryptography.RandomNumberGenerator]::GetBytes($Count); $rx=[byte[]]::new(4)
    for($i=0;$i -lt $Count;$i++){
        $b=[int]$random[$i]; $sp.Write($random,$i,1); for($j=0;$j -lt 4;$j++){$rx[$j]=$sp.ReadByte()}
        $actual=[Convert]::ToHexString($rx); $expected=('5631{0:X2}{1:X2}' -f ($i -band 255),(((($b -shl 3) -bor ($b -shr 5)) -band 255) -bxor 167)); $writer.WriteLine(('{0},{1:X2},{2}' -f $i,$b,$actual)); if($actual -cne $expected){throw "unexpected UART reply at $i expected $expected got $actual; $d"}
    }
    Start-Sleep -Milliseconds 50; if($sp.BytesToRead -ne 0){throw 'unexpected trailing bytes'}; $writer.Dispose(); $writer=$null
    [ordered]@{design=$r.design;utc=[DateTime]::UtcNow.ToString('o');port=$port;bit_sha256=$r.bit_sha256;rounds=$Count;reply_bytes=4*$Count;uart='115200 8N1';transcript_sha256=(Get-FileHash "$d/challenges.csv").Hash.ToLowerInvariant();configuration_readback='3 x DONE=1, CRC_ERROR=0';cpu_or_ddr_test=$false}|ConvertTo-Json|Set-Content "$d/pass.json"
    Write-Output "PHYSICAL_UART_PROBE_PASS $d"
} finally {if($writer){$writer.Dispose()}; $sp.Dispose(); if($job){if($job.State -notin 'Completed','Failed','Stopped'){Stop-Job $job}; Remove-Job $job -Force}}
