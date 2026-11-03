# Ask the ESP32 test sketch to run again ('r', or 'i' for the I2C test) and show its output.
# Usage:  & D:\ProtocolASIC\esp32\rerun.ps1 [-Port COM12]  (found automatically if not given) [-Seconds 40] [-Cmd i]
param([string]$Port = '', [int]$Seconds = 40, [string]$Cmd = 'r')
if (-not $Port) {   # find the ESP32's CH340 port (it moves when the USB plugs change)
    $Port = Get-CimInstance Win32_PnPEntity | ForEach-Object { if ($_.Name -match 'CH340.*[(](COM[0-9]+)[)]') { $Matches[1] } } | Select-Object -First 1
    if (-not $Port) { Write-Host 'No CH340 (ESP32) serial port found: is it plugged in?'; return }
    Write-Host "ESP32 found on $Port"
}
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open()
Start-Sleep -Milliseconds 300
$null = $sp.ReadExisting()
$sp.Write($Cmd)
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    $t = $sp.ReadExisting()
    if ($t) { Write-Host -NoNewline $t; if ($t -match "Send 'r'|==== (I2C|SPI) (PASS|FAIL)") { break } }
    Start-Sleep -Milliseconds 100
}
$sp.Close()
Write-Host "`n---- end ----"
