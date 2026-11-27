[CmdletBinding()] param(
 [Parameter(Mandatory)][string]$Run,[Parameter(Mandatory)][string]$Capture,[Parameter(Mandatory)][string]$Payload,
 [Parameter(Mandatory)][string]$Release,[Parameter(Mandatory)][string]$Out,[Parameter(Mandatory)][string]$Bridge,[ValidateSet('original','compilers','portable','tune','align','target')][string]$Experiment='original',
 [ValidateSet(12000,24000)][int]$Iterations=12000)
# Interleaved configurations with one steady board clock and one boot. The session marker
# is an ash variable, deliberately not a file that might survive guest restart.
$ErrorActionPreference='Stop';if($Iterations -ne 12000 -and $Experiment -ne 'target'){throw 'long fixed length is only reviewed for target'}
if(Test-Path -LiteralPath $Out){throw 'fresh output directory required'}
$dir=(New-Item -ItemType Directory -Path $Out).FullName;$tag=[guid]::NewGuid().ToString('n').Substring(0,16)
[IO.File]::WriteAllText((Join-Path $dir 'session.txt'),$tag)
$files=@{baseline='coremark.elf';o3='coremark-o3.elf';'o3-zb'='coremark-o3-zb.elf'}
$order='baseline','o3','o3-zb','o3','o3-zb','baseline','o3-zb','baseline','o3'
if($Experiment -eq 'compilers'){
 $trio='o3-zb','g15-zb-lto','o3-zb-lto-unroll';$order=@(for($r=0;$r -lt 3;$r++){for($c=0;$c -lt 3;$c++){$trio[($r+$c)%3]}})
 foreach($p in $trio){$files[$p]="coremark-$p.elf"}
}
if($Experiment -eq 'portable'){
 $trio='baseline','o3','g15-gc-lto';$files['g15-gc-lto']='coremark-g15-gc-lto.elf'
 $order=@(for($r=0;$r -lt 3;$r++){for($c=0;$c -lt 3;$c++){$trio[($r+$c)%3]}})
}
if($Experiment -eq 'tune'){
 $trio='baseline','g15-gc-lto','g15-gc-lto-ooo'
 foreach($p in $trio[1..2]){$files[$p]="coremark-$p.elf"}
 $order=@(for($r=0;$r -lt 3;$r++){for($c=0;$c -lt 3;$c++){$trio[($r+$c)%3]}})
}
if($Experiment -eq 'align'){
 $four='g15-gc-lto','g15-gc-lto-ooo-strict','g15-gc-lto-ooo','g15-gc-lto-relaxed'
 foreach($p in $four){$files[$p]="coremark-$p.elf"}
 $order=@(for($r=0;$r -lt 3;$r++){for($c=0;$c -lt 4;$c++){$four[($r+$c)%4]}})
}
if($Experiment -eq 'target'){
 $p='g15-gc-lto-ooo-strict'; $files[$p]="coremark-$p.elf"; $order=@($p,$p,$p)
 # Reject unknown hardware or foreign timing reports before the first timed run.
 & python "$PSScriptRoot/review-coremark-matrix.py" $Run $Capture $Payload $Release $dir --experiment target --iterations $Iterations --preflight
 if($LASTEXITCODE){throw 'physical target or software not eligible for benchmark'}
}
for($i=0;$i -lt $order.Count;$i++){
 $p=$order[$i];$dest=Join-Path $dir ('{0:d2}-{1}' -f ($i+1),$p)
 & "$PSScriptRoot/test-board-coremark.ps1" -Run $Run -Capture $Capture -Payload $Payload -Elf (Join-Path $Release $files[$p]) -Out $dest -Bridge $Bridge -Iterations $Iterations -Profile $p -SessionTag $tag -StartSession:($i -eq 0) -CheckTuneBoard:($Experiment -in @('tune','align','target')) -RequireReviewedMachine:($Experiment -eq 'target')
}
$summary=& python "$PSScriptRoot/review-coremark-matrix.py" $Run $Capture $Payload $Release $dir --experiment $Experiment --iterations $Iterations;if($LASTEXITCODE){throw 'matrix failed review'};$summary|Set-Content (Join-Path $dir result.json);$summary
