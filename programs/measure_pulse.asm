; Measure the length of each low pulse on pin in_base+0. Pushes the length in engine ticks, every pulse.
.wrap_target
    wait   1, rel 0          ; line idle (high)
    wait   0, rel 0          ; falling edge: pulse starts
    time   start
    wait   1, rel 0          ; rising edge: pulse ends
    time   capture isr       ; ISR = pulse length in ticks
    push   block
.wrap
