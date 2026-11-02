# Nonstop test: hold switch 1 on the Go Board while this runs.
# Counts the characters and lines received and checks every complete line is exactly right.
param([string]$Port = 'COM5', [int]$Seconds = 15)
$sp = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$sp.ReadBufferSize = 1MB
$sp.Open()
Write-Host "Listening for $Seconds s - hold switch 1 now"
$sb = New-Object System.Text.StringBuilder
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) { [void]$sb.Append($sp.ReadExisting()); Start-Sleep -Milliseconds 50 }
$sp.Close()
$text = $sb.ToString()
$lines = $text -split "`r`n"
$inner = if ($lines.Count -gt 2) { $lines[1..($lines.Count - 2)] } else { @() }   # drop partial first/last
$good = @($inner | Where-Object { $_ -eq 'Hello from Gosforth Skies' }).Count
$bad = @($inner | Where-Object { $_ -ne 'Hello from Gosforth Skies' })
Write-Host ("characters: {0}   complete lines: {1}   correct: {2}   wrong: {3}" -f $text.Length, $inner.Count, $good, $bad.Count)
Write-Host ("best second (theory at 115200 8N1 nonstop: 11520 chars/s)")
if ($bad.Count) { Write-Host "first wrong lines:"; $bad | Select-Object -First 5 | ForEach-Object { Write-Host "  [$_]" } }
