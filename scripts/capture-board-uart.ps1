[CmdletBinding()] param([Parameter(Mandatory)][ValidatePattern('^COM[0-9]+$')][string]$Port,
    [ValidateSet('linux','bare')][string]$Mode='linux', [ValidateRange(10,900)][int]$TimeoutSeconds=180)
# Connect before manually resetting the board. Reads UART; Linux mode only sends shell echo.
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent
if ($Port -notin [System.IO.Ports.SerialPort]::GetPortNames()) {throw "Port $Port not present. Identify the VCU118 UART in Device Manager."}
$dir=Join-Path $root logs; $path=Join-Path $dir ('board-uart-'+$Mode+'-'+[Guid]::NewGuid().ToString('N')+'.txt')
$sp=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One); $sp.Handshake='None'; $sp.DtrEnable=$false; $sp.RtsEnable=$false
$writer=$null; $text=''; $sent=$false; $nonce=[Guid]::NewGuid().ToString('N').Substring(0,10); $end=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
try {
 $sp.Open(); $writer=[IO.StreamWriter]::new($path,$false,[Text.UTF8Encoding]::new($false)); $writer.AutoFlush=$true; Write-Host "UART open on $Port. Reset the board now. Capture: $path"
 while([DateTime]::UtcNow -lt $end){
  $block=$sp.ReadExisting(); if (!$block) {Start-Sleep -Milliseconds 50;continue};$writer.Write($block); $text+=$block; if ($text.Length -gt 131072){$text=$text.Substring($text.Length-65536)}
  if($text -match 'Kernel panic|VCU118_DIAG_FAIL|SOC_SELFTEST_FAILED'){throw "Board reported a failure; see $path"}
  if($Mode -eq 'bare' -and $text -match '(?m)^VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r?$'){Write-Output "BARE_UART_PASS $path";return}
  if($Mode -eq 'linux' -and !$sent -and $text.Contains('VCU118_INITRAMFS_READY') -and $text.Contains('SOC_CHECK_PASS bytes=16777216')){
    $sp.Write("echo BOARD_"+'$((40+2))'+"_${nonce}`n");$sent=$true
  }
  if($sent -and $text -match "(?m)^(?:# )?BOARD_42_${nonce}\r?`n"){Write-Output "LINUX_UART_PASS $path";return}
 };throw "UART acceptance timed out; see $path"
} finally {if($writer){$writer.Dispose()}; $sp.Dispose()}
