[CmdletBinding()] param([string]$ToolBin='D:\Xilinx\Vitis\2024.2\gnu\riscv\nt\riscv64-unknown-elf\bin')
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent; $out=Join-Path $root 'artifacts\bare'; [void][IO.Directory]::CreateDirectory($out)
$cc=Join-Path $ToolBin 'riscv64-unknown-elf-gcc.exe'; $copy=Join-Path $ToolBin 'riscv64-unknown-elf-objcopy.exe'; $re=Join-Path $ToolBin 'riscv64-unknown-elf-readelf.exe'
Push-Location (Join-Path $root 'software\bare'); try {
 & $cc '-march=rv64imac_zicsr' '-mabi=lp64' '-mcmodel=medany' '-ffreestanding' '-nostdlib' '-nostartfiles' '-fno-pie' '-static' '-Os' '-Wall' '-Wextra' '-Werror' '-Wl,--build-id=none' '-T' 'layout.ld' 'entry.S' 'diagnose.c' -o "$out\bringup.elf"; if($LASTEXITCODE){throw 'compile failed'}
 & $copy -O binary "$out\bringup.elf" "$out\bringup.bin"; if($LASTEXITCODE){throw 'objcopy failed'}
 $h=(& $re -h "$out\bringup.elf") -join "`n"; if($LASTEXITCODE -or $h -notmatch 'ELF64' -or $h -notmatch 'RISC-V' -or $h -notmatch 'Entry point address:\s+0x80000000\b'){throw 'wrong ELF target or entry point'}
 $h | Out-File -Encoding ascii "$out\elf-header.txt"
 # Stage in a new regular file. Only replace our own named output once validation has succeeded.
 $tmp=Join-Path $out ('diag-'+[guid]::NewGuid().ToString('N')+'.img'); & python (Join-Path $root 'scripts\make_sd.py') "$out\bringup.bin" $tmp; if($LASTEXITCODE){throw 'GPT packing failed'}
 Move-Item -LiteralPath $tmp -Destination "$out\bringup-vcu118.img" -Force; Get-FileHash "$out\bringup-vcu118.img"; 'BARE_IMAGE_BUILD_OK'
} finally {Pop-Location}
