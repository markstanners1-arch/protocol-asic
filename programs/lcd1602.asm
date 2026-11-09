; HD44780 character display (LCD 1602 and the like) in 4-bit mode, write only: six output pins from a base pin P,
; D4-D7 on P..P+3, RS on P+4, E on P+5; the display's R/W pin tied to ground (it never drives its 5 V data lines back).
; On Tiny Tapeout P = 8: D4-D7 = uo[2..5], RS = uo[6], E = uo[7]. Proven on a model HD44780 (model/test_lcd.py).
; One engine tick = 1 us: clkdiv = f_clk * 1 us - 1 (40 MHz: 39; 50 MHz: 49; 12 MHz: 11).
; The host sends one 16-bit word per action, MSB first; the top 5 bits are the routine's address (assembler labels):
;   cmd:    word = cmd  << 11 | byte << 3 | long << 2      an instruction (RS low), two nibbles, high first
;   data:   word = data << 11 | byte << 3 | long << 2      a character (RS high)
;   nib:    word = nib  << 11 | nibble << 7                one nibble (RS low), then the long wait: the power-on
;                                                          sequence (0x3, 0x3, 0x3, 0x2) that puts the display in 4-bit mode
; After each byte the engine waits 64 us (an instruction takes 37 us, more on a slow display), or with long = 1 about
; 5.2 ms (clear and home take 1.52 ms; the power-on function sets want 4.1 ms). The host waits 40 ms after power-up first.
; Each nibble: data out, E high 1 us (450 ns or more), E low with the data held 1 us; E cycle 2 us (1000 ns or more).
; Config: out_base = set_base = P, set_count = 5, side_base = P + 5, side_count = 1, side_opt; out_right = 0 (MSB first).
.side_set 1 opt
    mov    osr, ~null      side 0  ; E low; OSR all ones
    out    pindirs, 6              ; drive D4-D7, RS and E (all low)
entry:
    pull   block                   ; next word from the host
    out    pc, 5                   ; top 5 bits = the routine
cmd:
    set    pins, 0                 ; RS low (D4-D7 low too, set again below)
    jmp    byte
data:
    set    pins, 16                ; RS high
byte:
    out    pins, 4                 ; high nibble on D4-D7 (RS kept)
    mov    y, y            side 1  ; E high
    mov    y, y            side 0  ; E low: the display takes the nibble; data held
    out    pins, 4                 ; low nibble
    mov    y, y            side 1
    mov    y, y            side 0
    out    x, 1                    ; the long-wait flag
    jmp    !x, short
long:
    set    x, 31
long_outer:
    set    y, 31
long_inner:
    jmp    y--, long_inner [4]     ; 32 x 5 us
    jmp    x--, long_outer         ; 32 x 162 us: about 5.2 ms
    jmp    entry
short:
    set    y, 31
short_loop:
    jmp    y--, short_loop [1]     ; 32 x 2 us: 64 us
    jmp    entry
nib:
    set    pins, 0                 ; RS low
    out    pins, 4                 ; the nibble
    mov    y, y            side 1
    mov    y, y            side 0
    jmp    long
