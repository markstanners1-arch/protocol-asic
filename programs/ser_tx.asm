; Frame sender on engine 0's serialiser (ISA v0.3), any line coding and bit order. 5 words.
; The host pushes a word count and then that many words; the serialiser sends them with whatever SERCFG sets (NRZ or
; Manchester, single-ended or differential, CRC append, end marker) and releases the pins to the levels set here.
; Unlike eth_tx.asm it does not read the TX FIFO level, so it works with out_right = 0 (MSB first) as well as 1.
; Settings: out_base = set_base = the first pin (the second is out_base + 1 if SERCFG [2]), out_count = set_count = 2.
    set    pindirs, 3            ; both pins driven
    set    pins, 0               ; both low between frames
.wrap_target
    pull   block                 ; the word count
    mov    ser, osr              ; start the serialiser; it pulls the words itself
    wait   0, ser                ; until the frame has gone out
.wrap
