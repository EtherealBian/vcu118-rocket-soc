# Dot-source in PowerShell 7. Select only the FPGA-side SCI of this CP2105 composite.
function Find-VcuFpgaUart([string]$BridgeSerial) {
    $parent = "USB\VID_10C4&PID_EA70\$BridgeSerial"
    $children = @(Get-PnpDevice -PresentOnly | Where-Object InstanceId -like 'USB\VID_10C4&PID_EA70&MI_01\*' | Where-Object {
        (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Parent -ErrorAction Stop).Data -eq $parent
    })
    if ($children.Count -ne 1) {throw "Expected exactly one FPGA-side CP2105 Standard interface for $parent; found $($children.Count)"}
    $id=$children[0].InstanceId; $code=(Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_ProblemCode).Data
    if ($code -ne 0) {throw "FPGA UART $id has Windows PnP problem code $code (28 = driver not installed). No serial I/O or programming performed."}
    $port=(Get-ItemProperty -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\$id\Device Parameters" -Name PortName -ErrorAction Stop).PortName
    if ($port -notmatch '^COM\d+$' -or $port -notin [IO.Ports.SerialPort]::GetPortNames()) {throw "No live COM port for $id"}; return $port
}
function Get-VcuConsoleEvent([string]$Text,[string]$Mode,[string]$Nonce,[bool]$ChallengeSent) {
    if ($Text -match 'Kernel panic|VCU118_DIAG_FAIL|SOC_SELFTEST_FAILED|ROM4_STOP|UART5_STOP') {return 'FAIL'}
    if ($Mode -eq 'bare') {
        if ($Text -match '(?ms)^VCU118_DIAG_START v1\r?\n.*?^VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r?\n') {return 'PASS'}
    } elseif ($Mode -eq 'linux') {
        if ($ChallengeSent -and $Text -match "(?m)^(?:# )?BOARD_42_${Nonce}\r?\n") {return 'PASS'}
        if (!$ChallengeSent -and $Text -match '(?ms)^VCU118_INITRAMFS_READY\r?\n.*?^SOC_CHECK_PASS bytes=16777216[^\r\n]*\r?\n.*?(?:^|\n)# ') {return 'CHALLENGE'}
    } else {throw 'unknown console test'}
    return 'WAIT'
}
