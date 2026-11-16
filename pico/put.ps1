# Copy files to the Pico 2's MicroPython over its serial port (raw REPL), no extra software needed.
# Usage:  & D:\ProtocolASIC\pico\put.ps1 chip_host.py programs.py id_test.py     (names are relative to this folder)
param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Files)
$Port = ''
if (-not $Port) {   # the Pico shows up as "USB Serial Device (COMn)" with USB ID 2E8A
    $Port = Get-CimInstance Win32_PnPEntity | ForEach-Object { if ($_.PNPDeviceID -match 'VID_2E8A' -and $_.Name -match '[(](COM[0-9]+)[)]') { $Matches[1] } } | Select-Object -First 1
    if (-not $Port) { Write-Host 'No Pico serial port found (VID 2E8A): is it plugged in and running MicroPython?'; return }
    Write-Host "Pico found on $Port"
}
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.DtrEnable = $true; $sp.RtsEnable = $true; $sp.ReadTimeout = 3000
$sp.Open()
function Read-Until([string]$want, [int]$ms = 4000) {
    $buf = ''; $end = (Get-Date).AddMilliseconds($ms)
    while ((Get-Date) -lt $end) { $buf += $sp.ReadExisting(); if ($buf.Contains($want)) { return $buf }; Start-Sleep -Milliseconds 20 }
    return $buf
}
try {
    $sp.Write([byte[]](3, 3), 0, 2); Start-Sleep -Milliseconds 300; $null = $sp.ReadExisting()   # Ctrl-C, Ctrl-C: stop anything running
    $sp.Write([byte[]](1), 0, 1)                                                                  # Ctrl-A: raw REPL
    $r = Read-Until 'raw REPL'; if (-not $r.Contains('raw REPL')) { throw "no raw REPL prompt: got '$r'" }
    $null = Read-Until '>' 1000
    foreach ($f in $Files) {
        $path = Join-Path $PSScriptRoot $f
        $bytes = [System.IO.File]::ReadAllBytes($path)
        $b64 = [Convert]::ToBase64String($bytes)
        $name = Split-Path $f -Leaf
        $mode = 'wb'
        for ($i = 0; $i -lt $b64.Length; $i += 400) {
            $chunk = $b64.Substring($i, [Math]::Min(400, $b64.Length - $i))
            $code = "import binascii`nf=open('$name','$mode')`nf.write(binascii.a2b_base64('$chunk'))`nf.close()`n"
            $sp.Write($code); $sp.Write([byte[]](4), 0, 1)
            $r = Read-Until ">" 4000
            if ($r -match 'Traceback') { throw "device error: $r" }
            $mode = 'ab'
        }
        Write-Host ("copied {0} ({1} bytes)" -f $name, $bytes.Length)
    }
    $sp.Write([byte[]](2), 0, 1)                                                                  # Ctrl-B: back to the friendly REPL
} finally { $sp.Close() }
