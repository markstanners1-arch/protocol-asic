; I2C master, both lines open drain (direction 1 = pull low, 0 = let go; pull-up resistors make the line high).
; SCL = the pin just below SDA, driven through the side-set's pin DIRECTIONS (side_dir); SDA through pin directions
; with SET and OUT. After every SCL release the program waits for SCL to really be high, so a slave that stretches
; the clock (holds SCL low while it thinks) is honoured.
; The host sends one 16-bit command word per action; the top 5 bits are the address of the routine (from the
; assembler's labels), so the program jumps straight to it:
;   start:  word = start << 11                        START, or repeated START
;   send:   word = send << 11 | byte << 3              send a byte; pushes the ACK bit (0 = the slave acked)
;   recv:   word = recv << 11 | ack << 10              read a byte; ack = 1 to ACK it (more wanted), 0 to NAK (last)
;   stop:   word = stop << 11                          STOP
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
send:
    set    x, 7
    mov    osr, ~osr                 ; a 1 bit must release SDA (direction 0), a 0 bit pull it low
send_bit:
    out    pindirs, 1    side 1 [3]  ; SDA = next bit while SCL is held low
    wait   1, rel 31     side 0 [3]  ; let SCL go; wait until it is high (the slave may stretch it); hold
    jmp    x--, send_bit side 1      ; SCL low
    set    pindirs, 0    side 1 [3]  ; release SDA for the slave's ACK
    wait   1, rel 31     side 0 [1]  ; SCL high
    in     pins, 1       side 0 [1]  ; sample SDA: 0 = ACK
    push   block         side 1      ; SCL low; report the ACK bit
    jmp    entry
recv:
    set    x, 7
recv_bit:
    set    pindirs, 0    side 1 [3]  ; SDA released: the slave drives it while SCL is low
    wait   1, rel 31     side 0 [1]  ; SCL high
    in     pins, 1       side 0 [1]  ; sample the bit
    jmp    x--, recv_bit side 1      ; SCL low
    out    pindirs, 1    side 1 [3]  ; our ACK (1 = pull SDA low) or NAK (0 = release)
    wait   1, rel 31     side 0 [3]  ; SCL high
    set    pindirs, 0    side 1 [1]  ; SCL low, release SDA
    push   block                     ; the byte
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
