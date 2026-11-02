# Ask the ESP32 test sketch to run again ('r') and show its output.
# Usage:  & D:\ProtocolASIC\esp32\rerun.ps1 [-Port COM7] [-Seconds 40]
param([string]$Port = 'COM7', [int]$Seconds = 40)
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.DtrEnable = $false; $sp.RtsEnable = $false
$sp.Open()
Start-Sleep -Milliseconds 300
$null = $sp.ReadExisting()
$sp.Write('r')
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    $t = $sp.ReadExisting()
    if ($t) { Write-Host -NoNewline $t; if ($t -match "Send 'r'") { break } }
    Start-Sleep -Milliseconds 100
}
$sp.Close()
Write-Host "`n---- end ----"
