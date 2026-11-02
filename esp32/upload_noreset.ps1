# Upload for ESP32 boards whose automatic download mode doesn't work (CH340 boards without the EN capacitor).
# First put the board in download mode by hand: hold BOOT, tap EN, release BOOT. Then run this.
# It does NOT reset the board before connecting (that would undo the manual download mode), and resets it
# afterwards so the new sketch starts. Then it shows the serial output.
# Usage:  & D:\ProtocolASIC\esp32\upload_noreset.ps1 [-Sketch spi_host_test] [-Port COM7] [-Seconds 40]
param([string]$Sketch = 'spi_host_test', [string]$Port = 'COM7', [int]$Seconds = 40)
$cli = "$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
$out = Join-Path $PSScriptRoot "build\$Sketch"
& $cli compile --fqbn esp32:esp32:esp32 --output-dir $out (Join-Path $PSScriptRoot $Sketch)
if ($LASTEXITCODE -ne 0) { Write-Host "Compile failed"; return }
$bin = Get-ChildItem $out -Filter "*.merged.bin" | Select-Object -First 1
if (-not $bin) { Write-Host "No merged .bin found in $out"; return }
$esptool = Get-ChildItem "$env:LOCALAPPDATA\Arduino15\packages\esp32\tools\esptool_py" -Recurse -Filter esptool.exe |
           Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
Write-Host "Uploading $($bin.Name) with $esptool"
& $esptool --chip esp32 --port $Port --baud 460800 --before no_reset --after hard_reset write_flash 0x0 $bin.FullName
if ($LASTEXITCODE -ne 0) { Write-Host "Upload failed: is the board in download mode (hold BOOT, tap EN, release BOOT)?"; return }
Write-Host "---- serial output from $Port for $Seconds s ----"
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open()
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    $t = $sp.ReadExisting()
    if ($t) { Write-Host -NoNewline $t }
    Start-Sleep -Milliseconds 100
}
$sp.Close()
Write-Host "`n---- end ----"
