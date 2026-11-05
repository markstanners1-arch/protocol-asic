# Run a script that is already on the Pico and show its output.
# Usage:  & D:\ProtocolASIC\pico\run.ps1 -Script id_test.py [-Seconds 20] [-Port COM13] [-Pre "CHIP_HZ=40_000_000"]
# -Pre: one line of Python run first (after the soft reset), to set a script's settings without editing it.
# A script that loops until a key is pressed stops when this window closes (the script sends Ctrl-C at the end).
param([string]$Script = 'id_test.py', [int]$Seconds = 15, [string]$Port = '', [string]$Pre = '')
if (-not $Port) {
    $Port = Get-CimInstance Win32_PnPEntity | ForEach-Object { if ($_.PNPDeviceID -match 'VID_2E8A' -and $_.Name -match '[(](COM[0-9]+)[)]') { $Matches[1] } } | Select-Object -First 1
    if (-not $Port) { Write-Host 'No Pico serial port found (VID 2E8A).'; return }
    Write-Host "Pico found on $Port"
}
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.DtrEnable = $true; $sp.RtsEnable = $true
$sp.Open()
try {
    $sp.Write([byte[]](3, 3), 0, 2); Start-Sleep -Milliseconds 300; $null = $sp.ReadExisting()
    $sp.Write([byte[]](4), 0, 1); Start-Sleep -Milliseconds 1500; $null = $sp.ReadExisting()     # Ctrl-D: soft reset, so edited modules load afresh
    if ($Pre) { $sp.Write("$Pre`r"); Start-Sleep -Milliseconds 300; $null = $sp.ReadExisting() }
    $sp.Write("exec(open('$Script').read())`r")
    $null = $sp.ReadLine()    # the echoed command line
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        $t = $sp.ReadExisting()
        if ($t) { Write-Host -NoNewline $t; if ($t -match 'PASS|FAIL|Traceback') { Start-Sleep -Milliseconds 400; Write-Host -NoNewline $sp.ReadExisting(); break } }
        Start-Sleep -Milliseconds 50
    }
    $sp.Write([byte[]](3, 3), 0, 2)
} finally { $sp.Close() }
Write-Host "`n---- end ----"
