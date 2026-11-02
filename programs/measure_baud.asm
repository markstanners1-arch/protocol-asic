; Measure the other end's bit time from one 'U' (0x55): its start bit is the first low pulse.
; Pushes the start bit's length in engine ticks to the host.
    wait   1, pin 0          ; first see the line idle (high): never trust a low straight after reset
    wait   0, pin 0          ; falling edge: start bit begins
    time   start
    wait   1, pin 0          ; rising edge: start bit ends (0x55's bit 0 is a 1)
    time   capture isr       ; ISR = one bit time, in ticks
    push   block
done:
    jmp    done
