[CmdletBinding()] param([string]$ToolBin='D:\Xilinx\Vitis\2024.2\gnu\riscv\nt\riscv64-unknown-elf\bin')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$src=Join-Path $root 'third_party\chipyard\fpga\src\main\resources\vcu118\sdboot'
$out=Join-Path $root 'artifacts\rom100'; [void][IO.Directory]::CreateDirectory($out)
$gcc=Join-Path $ToolBin 'riscv64-unknown-elf-gcc.exe'; $objcopy=Join-Path $ToolBin 'riscv64-unknown-elf-objcopy.exe'; $readelf=Join-Path $ToolBin 'riscv64-unknown-elf-readelf.exe'
Push-Location $src
try {
 & $gcc --version; if($LASTEXITCODE){throw 'GCC unavailable'}
 & $gcc -march=rv64ima_zicsr_zifencei -mcmodel=medany -O2 -std=gnu11 -Wall -nostartfiles -fno-common -g -DENTROPY=0 -mabi=lp64 -DNONSMP_HART=0 -DTL_CLK=100UL -Iinclude -I. -static -nostdlib '-Wl,--build-id=none' -Llinker '-T' 'linker/sdboot.elf.lds' -o "$out\sdboot.elf" head.S sd.c kprintf.c
 if($LASTEXITCODE){throw 'ROM link failed'}
 & $objcopy -O binary --change-addresses=-0x10000 "$out\sdboot.elf" "$out\sdboot.bin"; if($LASTEXITCODE){throw 'objcopy failed'}
 $h=(& $readelf -h "$out\sdboot.elf") -join "`n"; if($LASTEXITCODE -or $h -notmatch 'RISC-V' -or $h -notmatch 'Entry point address:\s+0x10000\b'){throw 'unexpected ELF'}
 $b=Get-Item "$out\sdboot.bin"; if($b.Length -le 0 -or $b.Length -ge 65536){throw 'invalid ROM binary size'}
 $h | Out-File -Encoding ascii "$out\elf-header.txt"; Get-FileHash -Algorithm SHA256 "$out\sdboot.bin"; "ROM_BUILD_OK bytes=$($b.Length) address=0x10000 pbus_MHz=100"
} finally {Pop-Location}
