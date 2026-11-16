# Read the Go Board's serial output for a few seconds (COM5, 115200 8N1).
# Usage:  & D:\ProtocolASIC\fpga\go_board\listen.ps1 [-Port COM5] [-Seconds 5]
param([string]$Port = 'COM5', [int]$Seconds = 5)
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.ReadTimeout = 500
$sp.Open()
$end = (Get-Date).AddSeconds($Seconds)
$text = ''
while ((Get-Date) -lt $end) {
    try { $text += $sp.ReadExisting() } catch {}
    Start-Sleep -Milliseconds 100
}
$sp.Close()
Write-Host "---- $Seconds s on $Port, $($text.Length) characters ----"
Write-Host $text
