; I2C master. SCL = engine pin 0 (side-set, driven), SDA = engine pin 1 (open drain: direction 1 = pull low,
; 0 = let go, the pull-up resistor makes it high). The host sends one 16-bit command word per action; the top
; 5 bits are the address of the routine (from the assembler's labels), so the program jumps straight to it:
;   start:  word = start << 11                        START, or repeated START
;   send:   word = send << 11 | byte << 3              send a byte; pushes the ACK bit (0 = the slave acked)
;   recv:   word = recv << 11 | ack << 10              read a byte; ack = 1 to ACK it (more wanted), 0 to NAK (last)
;   stop:   word = stop << 11                          STOP
; One bit = 10 engine ticks (SCL low 5, high 5; every low and high is at least 5 ticks, so at 100 kHz the
; standard's 4.7 us / 4.0 us minimums hold), so SCL = f_clk / (10 * (clkdiv + 1)); e.g. 50 MHz, clkdiv 49 -> 100 kHz.
; Config: side_base = 0, side_count = 1; set_base = 0, set_count = 2 (SCL and SDA directions);
;         out_base = in_base = 1, out_count = 1; out_right = in_right = 0 (MSB first).
.side_set 1 opt
    set    pindirs, 1    side 1      ; power-up: drive SCL (high), release SDA
entry:
    pull   block         [1]         ; next command word from the host (SCL stays where the last routine left it)
    out    pc, 5                     ; top 5 bits = the routine
send:
    set    x, 7
    mov    osr, ~osr                 ; a 1 bit must release SDA (direction 0), a 0 bit pull it low
send_bit:
    out    pindirs, 1    side 0 [3]  ; SDA = next bit while SCL is low
    mov    y, y          side 1 [4]  ; SCL high: the slave samples
    jmp    x--, send_bit side 0      ; SCL low
    set    pindirs, 1    side 0 [3]  ; release SDA for the slave's ACK
    mov    y, y          side 1 [2]  ; SCL high
    in     pins, 1       side 1 [1]  ; sample SDA: 0 = ACK
    push   block         side 0      ; SCL low; report the ACK bit
    jmp    entry
recv:
    set    x, 7
recv_bit:
    set    pindirs, 1    side 0 [3]  ; SDA released: the slave drives it while SCL is low
    mov    y, y          side 1 [2]  ; SCL high
    in     pins, 1       side 1 [1]  ; sample the bit
    jmp    x--, recv_bit side 0      ; SCL low
    out    pindirs, 1    side 0 [3]  ; our ACK (1 = pull SDA low) or NAK (0 = release)
    mov    y, y          side 1 [4]  ; SCL high
    set    pindirs, 1    side 0 [1]  ; SCL low, release SDA
    push   block                     ; the byte
    jmp    entry
start:
    mov    y, y          side 1 [4]  ; SCL high (SDA is released after any routine, or on an idle bus)
    set    pindirs, 3    side 1 [3]  ; SDA falls while SCL is high: START
    jmp    entry         side 0 [3]  ; SCL low
stop:
    set    pindirs, 3    side 0 [3]  ; SDA low while SCL is low
    mov    y, y          side 1 [3]  ; SCL high
    set    pindirs, 1    side 1 [3]  ; SDA rises while SCL is high: STOP; bus idle
    jmp    entry
