; I2C master, both lines open drain (direction 1 = pull low, 0 = let go; pull-up resistors make the line high).
; SCL = the pin just below SDA, driven through the side-set's pin DIRECTIONS (side_dir); SDA through pin directions
; with SET and OUT. After every SCL release the program waits for SCL to really be high, so a slave that stretches
; the clock (holds SCL low while it thinks) is honoured.
; The host sends one 16-bit command word per action; the top 5 bits are the address of the routine (from the
; assembler's labels), so the program jumps straight to it:
;   start:  word = start << 11                        START, or repeated START
;   xfer:   word = xfer << 11 | byte << 3 | ack << 2  one byte either way: the nine SDA LEVELS the master puts on the
;           wire, MSB first (eight data bits, then the ninth = ACK slot). Pushes back the nine levels SEEN on the wire
;           as (byte on the wire) << 1 | (ACK bit), the same format as the sniffer.
;             send a byte:  byte, ack = 1 (SDA released in the ACK slot). Reply: byte << 1 | 0 if the slave acked;
;                           a different byte means another master pulled SDA low (arbitration lost).
;             read a byte:  byte = 0xFF (SDA released, the slave drives it), ack = 0 to ACK (more wanted), 1 to NAK
;                           (the last byte). Reply: the slave's byte << 1 | our ACK bit.
;   stop:   word = stop << 11                         STOP
; One routine for send and receive (3 Nov 2026, was two: 30 words, now 19) because both are the same nine clocks;
; only the levels on SDA differ, and those come from the host's word.
; One bit = 10 engine ticks (SCL low 5, high 5 from when SCL is seen high), so with no stretching
; SCL = f_clk / (10 * (clkdiv + 1)); e.g. 50 MHz, clkdiv 49 -> 100 kHz, and the standard's 4.7 / 4.0 us minimums hold.
; Use clkdiv >= 2: below that the 2-clock input synchroniser makes the engine see its own SCL release a tick late,
; and the high time grows by a tick (still correct, just not 10 ticks).
; Config: side_base = SCL, side_count = 1, side_dir = 1 (side_opt from the directive); set_base = out_base = in_base
;         = SDA, set_count = 1, out_count = 1; out_right = in_right = 0 (MSB first). The waits on SCL use rel 31,
;         i.e. in_base - 1 (pin numbers wrap mod 32), so the pair can sit anywhere: SCL = pin n, SDA = pin n + 1.
.side_set 1 opt pindirs
    set    pindirs, 0    side 0      ; power-up: let go of SDA and SCL (both idle high through the pull-ups)
entry:
    pull   block         [1]         ; next command word from the host (SCL stays where the last routine left it)
    out    pc, 5                     ; top 5 bits = the routine
xfer:
    mov    osr, ~osr                 ; SDA levels -> directions: a 1 bit releases SDA (direction 0), a 0 pulls it low
    set    x, 8                      ; nine bits: eight data, then the ACK slot
xfer_bit:
    out    pindirs, 1    side 1 [3]  ; SDA = next level while SCL is held low
    wait   1, rel 31     side 0 [1]  ; let SCL go; wait until it is high (the slave may stretch it); hold
    in     pins, 1       side 0 [1]  ; sample SDA as it is on the wire
    jmp    x--, xfer_bit side 1      ; SCL low
    set    pindirs, 0    side 1      ; release SDA (we may have held it low for an ACK)
    push   block                     ; the nine levels seen: byte << 1 | ACK bit
    jmp    entry
start:
    wait   1, rel 31     side 0 [3]  ; SCL high (already, on an idle bus; SDA is released after any routine)
    set    pindirs, 1    side 0 [3]  ; SDA falls while SCL is high: START
    jmp    entry         side 1 [3]  ; SCL low
stop:
    set    pindirs, 1    side 1 [3]  ; SDA low while SCL is low
    wait   1, rel 31     side 0 [3]  ; SCL high
    set    pindirs, 0    side 0 [3]  ; SDA rises while SCL is high: STOP; bus idle
    jmp    entry
