# Resume inside the current build as soon as the running pinned submodule setup has finished.
$ErrorActionPreference='Stop'; $root=Split-Path $PSScriptRoot -Parent
$envFile=Join-Path $root 'third_party\chipyard\env.sh'; $limit=(Get-Date).AddHours(2)
while (!(Test-Path -LiteralPath $envFile -PathType Leaf) -or !(Select-String -Quiet -LiteralPath $envFile -SimpleMatch 'software/firemarshal:$PATH')) {
 if ((Get-Date) -ge $limit){throw 'submodule init did not finish within the wait window; check init-generator.txt'}
 Start-Sleep -Seconds 20
}
& (Join-Path $PSScriptRoot 'build-fpga.ps1')
