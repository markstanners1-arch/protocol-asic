# Compile and upload an ESP32 sketch, then show its serial output for a while.
# Usage:  & D:\ProtocolASIC\esp32\upload_and_watch.ps1 [-Sketch spi_host_test] [-Port COM12]  (found automatically if not given) [-Seconds 40]
param([string]$Sketch = 'spi_host_test', [string]$Port = '', [int]$Seconds = 40)
if (-not $Port) {   # find the ESP32's CH340 port (it moves when the USB plugs change)
    $Port = Get-CimInstance Win32_PnPEntity | ForEach-Object { if ($_.Name -match 'CH340.*[(](COM[0-9]+)[)]') { $Matches[1] } } | Select-Object -First 1
    if (-not $Port) { Write-Host 'No CH340 (ESP32) serial port found: is it plugged in?'; return }
    Write-Host "ESP32 found on $Port"
}
$cli = "$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
$dir = Join-Path $PSScriptRoot $Sketch
& $cli compile --fqbn esp32:esp32:esp32 --upload --port $Port $dir
if ($LASTEXITCODE -ne 0) { Write-Host "Upload failed (exit $LASTEXITCODE)"; return }
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
