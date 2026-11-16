# Listens to the Go Board bounce meter (bounce_top) and prints each press/release in plain English.
# Usage:  & D:\ProtocolASIC\fpga\go_board\bounce_listen.ps1 [-Port COM5] [-Seconds 180] [-Log file.csv]
param([string]$Port = 'COM5', [int]$Seconds = 180, [string]$Log = "$PSScriptRoot\bounce_log.csv")
$names = @{0='off'; 1='~10 us'; 2='~82 us'; 3='~655 us'; 4='~2.6 ms'; 5='~10.5 ms'}
if (-not (Test-Path $Log)) { 'time,event,level,raw_edges,filtered_edges,bounce_us,filter_delay_us,setting' | Out-File $Log -Encoding ascii }
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.ReadTimeout = 500; $sp.NewLine = "`n"
$sp.Open()
Write-Host "Listening on $Port for $Seconds s. Press switch 1 (the test switch); switch 2 steps the filter setting."
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    try { $line = $sp.ReadLine().Trim() } catch { continue }
    if ($line -match '^(E|S) L(\d) R([0-9A-F]{4}) F([0-9A-F]{4}) B([0-9A-F]{4}) D([0-9A-F]{4}) M(\d)$') {
        $k = $Matches[1]; $lvl = [int]$Matches[2]; $r = [Convert]::ToInt32($Matches[3],16); $f = [Convert]::ToInt32($Matches[4],16)
        $b = [Convert]::ToInt32($Matches[5],16); $d = [Convert]::ToInt32($Matches[6],16); $m = [int]$Matches[7]
        if ($k -eq 'S') { Write-Host ("-- filter setting {0} ({1})" -f $m, $names[$m]) -ForegroundColor Cyan }
        else {
            $what = if ($lvl) { 'press  ' } else { 'release' }
            $ok = if ($f -eq 1) { 'clean' } else { "$f edges got through" }
            Write-Host ("{0}: {1,3} raw edges -> {2,-18} bounce {3,6} us   filter delay {4,6} us   [setting {5}, {6}]" -f $what, $r, $ok, $b, $d, $m, $names[$m])
        }
        "{0},{1},{2},{3},{4},{5},{6},{7}" -f (Get-Date -Format s), $k, $lvl, $r, $f, $b, $d, $m | Out-File $Log -Append -Encoding ascii
    } elseif ($line) { Write-Host "?? $line" }
}
$sp.Close()
Write-Host "Done. Log: $Log"
