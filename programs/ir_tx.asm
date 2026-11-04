; NEC infrared transmitter (4 Nov 2026): the partner of ir_nec.asm. Drives one pin with the 38 kHz carrier in bursts, ready for an IR LED.
; The host pushes two words per frame, exactly the two words ir_nec.asm pushes: address | ~address << 8, then command | ~command << 8
; (the host builds the inverses, so extended 16-bit addresses and the odd remotes seen on the bench go through as well).
; A frame is sent as soon as the first word arrives; the host paces frames (108 ms apart for a held button).
; Tick = a third of a carrier cycle, 8.67 us (clkdiv 103 at 12 MHz, 433 at 50 MHz). A carrier cycle is three instructions: pin high
; (1 tick), pin low (1 tick), loop (1 tick) = 38.4 kHz in a bit burst, a one third duty cycle kind to an LED. The leader's two loops add
; 2 ticks per 30 cycles, which pulls its average to 37.7 kHz: the two straddle 38 kHz, inside every receiver's band.
;   leader burst  11 x 30 cycles = 330 cycles = 1012 ticks       = 8.8 ms  (9 ms nominal)
;   leader space  16 x 32 ticks                                   = 4.5 ms
;   bit burst     21 cycles = 63 ticks                           = 0.55 ms (562.5 us nominal; 0.53 ms edge to edge)
;   0 space       62 ticks + the 2-3 ticks of loop overhead       = 0.57 ms
;   1 space       as a 0, plus 4 x 32 ticks                      = 1.70 ms  (1687.5 us nominal)
;   one space a frame (after bit 16) is 5 ticks (44 us) longer: the second word is fetched there
;   closing burst 21 cycles, the line then stays low
; Within 3 % of NEC everywhere (one space 8 %), and the receiver ICs accept 10 %. The repeat frame (9 ms, 2.25 ms, burst) is not generated: a
; held button is sent as repeated data frames by the host, which every NEC receiver also accepts.
; Bits come from the OSR LSB first (out_right = 1); `jmp !osre` runs the 16 bits of a word, and the ISR (never otherwise used)
; remembers which word of the frame is being sent: 0 first, all ones second.
; Config: set_base = the LED pin (an out-only pin such as 9: its direction is set here), set_count = 1, out_right = 1; no side-set.
    set    pindirs, 1            ; drive the LED pin (it idles low: LED off)
.wrap_target
idle:
    pull   block                 ; address word: waits here, line low, for the host
    mov    isr, null             ; first word of the frame
    set    x, 10                 ; leader burst: 11 outer x 30 inner cycles
lead_o:
    set    y, 29
lead_i:
    set    pins, 1
    set    pins, 0
    jmp    y--, lead_i           ; 3 ticks a cycle
    jmp    x--, lead_o
    set    x, 15                 ; leader space: 16 x 32 ticks
lead_s:
    jmp    x--, lead_s  [31]
bit:
    out    x, 1                  ; next bit, LSB first
    set    y, 20                 ; bit burst: 21 cycles
burst:
    set    pins, 1
    set    pins, 0
    jmp    y--, burst
    mov    y, y         [31]     ; space: 32 + 30 ticks, plus a few of overhead
    mov    y, y         [29]
    jmp    !x, next              ; a 0 is done
    set    x, 3                  ; a 1 waits 4 x 32 ticks more
long:
    jmp    x--, long    [31]
next:
    jmp    !osre, bit            ; more bits in this word
    mov    x, isr                ; word finished: which one was it?
    jmp    !x, word2             ; the first: fetch the second
    set    y, 20                 ; the second: the closing burst
final:
    set    pins, 1
    set    pins, 0
    jmp    y--, final
.wrap                            ; back to idle: the line stays low
word2:
    mov    isr, ~null            ; mark the second word
    pull   block
    jmp    bit
