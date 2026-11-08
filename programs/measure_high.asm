; Measure the length of each high pulse on pin in_base+0 (the mirror of measure_pulse.asm, for lines that idle low:
; an SPI clock in mode 0, an active-high data line). Pushes the length in engine ticks, every pulse.
.wrap_target
    wait   0, rel 0          ; line idle (low)
    wait   1, rel 0          ; rising edge: pulse starts
    time   start
    wait   0, rel 0          ; falling edge: pulse ends
    time   capture isr       ; ISR = pulse length in ticks (saturates at 65535)
    push   block
.wrap
