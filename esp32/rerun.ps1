# Ask the ESP32 test sketch to run again ('r', or 'i' for the I2C test) and show its output.
# Usage:  & D:\ProtocolASIC\esp32\rerun.ps1 [-Port COM7] [-Seconds 40] [-Cmd i]
param([string]$Port = 'COM7', [int]$Seconds = 40, [string]$Cmd = 'r')
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
