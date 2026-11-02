; Diagnostic: keep pushing the raw pin levels (16 pins from in_base) to the host. Drops when the FIFO is full.
loop:
    mov    isr, pins
    push   noblock
    jmp    loop
