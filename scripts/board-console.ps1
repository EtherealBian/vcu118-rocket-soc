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
    if ($Text -match 'Kernel panic|VCU118_DIAG_FAIL|VCU118_ADDR_FAIL|SOC_SELFTEST_FAILED|VCU118_COUNTER_FAIL|VCU118_SWEEP_FAIL|DOT4_MMIO_FAIL|DOT4_FAIL|LINUX_DOT4_FAILED|ROM4_STOP|UART5_STOP') {return 'FAIL'}
    if ($Mode -eq 'bare') {
        if ($Text -match '(?ms)^VCU118_DIAG_START v1\r?\n.*?^VCU118_DIAG_PASS memory_bytes=1048576 passes=2 timer=advanced\r?\n') {return 'PASS'}
    } elseif ($Mode -eq 'address') {
        if ($Text -cmatch '(?ms)^VCU118_ADDR_START v1\r?\n.*?^VCU118_ADDR_PASS windows=4 bytes_each=4096 passes=2 flush_lines=512\r?\n') {return 'PASS'}
    } elseif ($Mode -eq 'sweep') {
        if ($Text -cmatch '(?ms)^VCU118_SWEEP_START v1 block_mib=8 blocks=254\r?\n.*?^VCU118_SWEEP_PASS bytes=2130706432 passes=2\r?\n') {return 'PASS'}
    } elseif ($Mode -eq 'counters') {
        if ($Text -cmatch '(?ms)^VCU118_COUNTER_START v1 n=131072\r?\n.*?^VCU118_COUNTER_PASS kernels=3 rounds=3\r?\n') {return 'PASS'}
    } elseif ($Mode -eq 'dot4') {
        if ($Text -cmatch '(?m)^DOT4_MMIO_START\r?\nDOT4_MMIO_PASS vectors=257 protocol_errors_checked=2\r?\n') {return 'PASS'}
    } elseif ($Mode -in 'linux','linux-dot4') {
        if ($Mode -eq 'linux-dot4' -and $Text.Contains('LINUX_DOT4_NO_PLATFORM_DEVICE')) {return 'FAIL'}
        if ($ChallengeSent -and $Text -match "(?m)^(?:# )?BOARD_42_${Nonce}\r?\n") {return 'PASS'}
        if (!$ChallengeSent -and $Text -match '(?ms)^VCU118_INITRAMFS_READY\r?\n.*?^SOC_CHECK_PASS bytes=16777216 passes=[1-9]\d* elapsed_s=\d+\r?\n.*?(?:^|\n)# ') {
            if ($Mode -eq 'linux-dot4' -and $Text -cnotmatch '(?ms)^SOC_CHECK_PASS [^\n]+\n.*?^LINUX_DOT4_PASS vectors=257 reserved_rejected=1\r?\n.*?^# ') {return 'WAIT'}
            return 'CHALLENGE'
        }
    } else {throw 'unknown console test'}
    return 'WAIT'
}

# Return $null until an entire ROM marker arrives. Keep bytes following that
# marker: the guest may already have printed its first line in the same read.
function Get-VcuPostHandoffText([string]$Text) {
    $m=[regex]::Match($Text,'(?m)^UART5_HANDOFF\r?\n')
    if (!$m.Success) {return $null}
    return $Text.Substring($m.Index+$m.Length)
}
