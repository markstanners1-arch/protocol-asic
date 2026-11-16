; DALI forward frame transmitter (4 Nov 2026, IEC 62386-101 basics). The host pushes one 16-bit word per frame, address byte
; in the top byte and the command or level byte in the bottom (0xFEFE = broadcast DAPC 254, 0xFFA0 = QUERY ACTUAL LEVEL);
; the engine sends it as a start bit, the 16 bits MSB first, then holds the bus idle for 9.5 ms (the standard's 9.17 ms
; settling before the next forward frame), so the host may queue frames in the FIFO and they go out correctly spaced.
; Manchester at 1200 bit/s: a bit is 833.3 us in two halves; a logical 1 is bus LOW then HIGH (rising edge mid-bit), a 0 is
; HIGH then LOW. The start bit is a 1. Idle is bus high.
; Tick = an eighth of a bit, 104.17 us:  clkdiv = f_clk / 9600 - 1 = 1249 at 12 MHz, 5207 at 50 MHz (both well inside 16 bits).
; A half bit is 4 ticks; the first half is one instruction with a delay of 3, the second half is the inversion, the next bit's
; fetch and the loop jump (2 + 1 + 1 ticks), so every half is exactly 4 ticks: no clock error at all, the divider's rounding
; is the only one (0.006 % at 50 MHz).
; POLARITY: the TX pin drives an NPN base through 1 k, the transistor across the bus: pin HIGH = bus shorted = bus LOW,
; pin LOW = transistor off = bus released = HIGH. So the pin idles LOW (and an unowned output pin, driven low by the chip,
; leaves the bus alone). For a driver that is not inverting (a MOSFET gate driver module, an opto with its output pulled
; up on the bus side), swap the four pin writes: set pins, 0 for the start bit's first half and 1 for its second, mov pins, ~x
; then mov pins, x in the bit loop, and set pins, 1 for the stop (and the idle after set pindirs); nothing else changes.
; Config: out_base = set_base = the TX pin (an output-only pin, 8 on the bench), out_count = set_count = 1, out_right = 0
; (MSB first); no side-set, no inputs. 13 words.
    set    pindirs, 1            ; drive the TX pin; it was low (bus released) and stays low until a frame
.wrap_target
    pull   block                 ; a frame word from the host; the bus idles high meanwhile
    set    pins, 1      [3]      ; start bit, first half: transistor on, bus low            4 ticks
    set    pins, 0      [1]      ; start bit, second half: bus high                         2 ticks ...
    set    y, 15                 ; 16 data bits                                             1
    out    x, 1                  ; the first bit (MSB)                                      1  = 4
bit:
    mov    pins, x      [3]      ; first half: pin = bit, so the bus is NOT bit (a 1 shorts the bus first)   4 ticks
    mov    pins, ~x     [1]      ; second half: bus = bit                                   2 ticks ...
    out    x, 1                  ; the next bit                                             1
    jmp    y--, bit              ;                                                          1  = 4
    set    pins, 0               ; stop: bus released; it stays high for 2 + 88 ticks before the next frame can start
    set    x, 21                 ; 22 loops of 4 ticks = 88 ticks = 9.17 ms: the settling time between forward frames
gap:
    jmp    x--, gap     [3]
.wrap                            ; back to the pull: a queued frame starts 9.5 ms after this one ended
