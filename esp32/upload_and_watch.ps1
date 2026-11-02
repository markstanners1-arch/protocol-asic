# Compile and upload an ESP32 sketch, then show its serial output for a while.
# Usage:  & D:\ProtocolASIC\esp32\upload_and_watch.ps1 [-Sketch spi_host_test] [-Port COM7] [-Seconds 40]
param([string]$Sketch = 'spi_host_test', [string]$Port = 'COM7', [int]$Seconds = 40)
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
