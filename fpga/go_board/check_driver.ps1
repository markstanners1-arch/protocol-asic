# Show which driver each half of the Go Board's FTDI chip is using.
# Interface 0 (MI_00) should be WinUSB for flashing; interface 1 (MI_01) stays FTDIBUS (the COM port).
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_0403&PID_6010&MI_0' } | ForEach-Object {
    $svc = (Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Service).Data
    '{0,-28} {1,-8} driver: {2}' -f $_.FriendlyName, ($_.InstanceId -replace '.*(MI_0\d).*', '$1'), $svc
}
