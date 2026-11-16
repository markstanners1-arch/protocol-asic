# Flash the Go Board from an ordinary PowerShell window (outside Claude's sandbox).
# Usage:  & D:\ProtocolASIC\fpga\go_board\flash.ps1 [bitstream]   (default: build\hello.bin)
param([string]$Bin = "$PSScriptRoot\build\hello.bin")
$suite = 'D:\Tools\oss-cad-suite'
$env:PATH = "$suite\bin;$suite\lib;$env:PATH"
Write-Host "Flashing $Bin"
& "$suite\bin\iceprog.exe" $Bin
Write-Host "iceprog exit code: $LASTEXITCODE"
