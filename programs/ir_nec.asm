; NEC infrared remote decoder (4 Nov 2026). The receiver module (KY-022 or any 38 kHz demodulator) on engine pin 1:
; idles high, low while a carrier burst is on. An NEC frame is a 9 ms burst, a 4.5 ms space, then 32 bits LSB first
; (address, ~address, command, ~command), each a 562.5 us burst followed by a 562.5 us space (0) or a 1687.5 us
; space (1), then a closing 562.5 us burst. A held button sends a repeat frame every 108 ms: 9 ms burst, 2.25 ms
; space, 562.5 us burst.
; Method: every length is judged by a counting loop that polls the pin every iteration with jmp pin, loading X with
; the number of iterations first: if the line changes before X runs out the pulse was short, if X runs out it was long
; (and then wait for the real edge). No stopwatch, no compare instruction needed. Three thresholds:
;   leader burst   low  >= 4.5 ms (set x, 22: 23 polls 4 ticks apart, the last 90 ticks after the edge was seen)
;                  else it was noise or a stray bit: back to idle
;   leader space   high >= 3.3 ms (set x, 16: 17 polls 4 ticks apart, the last at 66 ticks): a data frame follows;
;                  shorter (2.25 ms): a repeat frame
;   bit space      high >= 1.1 ms (set x, 10: 11 polls 2 ticks apart, the last at 22 ticks): a 1; shorter: a 0
; (A loop loaded with N runs its poll N+1 times: jmp x-- falls through when X is already 0.)
; Margins either side of the nominal lengths: about 1.1 ms for the two leader judgements, 0.55 ms for a bit
; (562.5 us against 1687.5 us), so a remote 5 % fast or slow (cheap crystals, warm rooms) still decodes, and a
; receiver edge seen a tick late does not matter.
; Bits shift into the ISR right (LSB first) and `push iffull` sends each 16 as it fills: two words a frame,
; address | ~address << 8 first, then command | ~command << 8. The host checks the inverses and pairs the words
; (the second follows the first within 36 ms). A repeat frame pushes 0xFFFF, which no NEC half-frame can be
; (its top byte would have to be the inverse of its bottom byte).
;   1-bit space    abandoned if still high after another 2.4 ms (the frame was cut short): back to idle, so a
;                  broken frame cannot leave the bit loop waiting into the next frame
; Tick = 50 us (clkdiv 599 at 12 MHz, 2499 at 50 MHz). A frame takes 67.5 ms at most; the ISR is cleared at
; every leader so a frame cut short cannot leave stray bits for the next one (the host sees an unpaired word).
; Config: in_base = 1 (the receiver), jmp_pin = 1, in_right = 1 (LSB first); no outputs, no side-set. 29 words.
.wrap_target
idle:
    wait   1, rel 0              ; line idle (high); also covers the synchroniser's reset-low
    wait   0, rel 0              ; a burst starts
    set    x, 22                 ; leader burst: must still be low at the 23rd poll, 90 ticks = 4.5 ms on
burst:
    jmp    pin, idle             ; rose already: too short for a leader, start again
    jmp    x--, burst  [2]
    wait   1, rel 0              ; the leader burst ends: time its space
    set    x, 16                 ; still high at the 17th poll, 66 ticks = 3.3 ms on: a data frame
space:
    jmp    pin, long             ; still high
    mov    isr, ~null            ; fell before 3.3 ms: a repeat frame. Push the 0xFFFF marker
    push   noblock
    jmp    idle
long:
    jmp    x--, space  [2]
    wait   0, rel 0              ; 3.3 ms and still high: a data frame. Wait for the first bit's burst
    mov    isr, null             ; empty ISR, 32 bits to come
    set    y, 31
bit:
    wait   1, rel 0              ; bit burst ends: time its space
    set    x, 10                 ; still high at the 11th poll, 22 ticks = 1.1 ms on: a 1
poll:
    jmp    pin, high
    in     null, 1               ; fell before 1.1 ms: a 0
    jmp    next
high:
    jmp    x--, poll
    in     x, 1                  ; 1.1 ms and still high: a 1 (X has just wrapped to 0xFFFF, so its low bit is 1)
    set    x, 12                 ; its space must end within another 2.5 ms (13 polls 4 ticks apart)
tail:
    jmp    pin, still
    jmp    next                  ; the real end of the space
still:
    jmp    x--, tail  [2]
    jmp    idle                  ; stuck high: the frame was cut short (hand in the beam); the next leader starts afresh
next:
    push   iffull noblock        ; every 16 bits: the address pair, then the command pair
    jmp    y--, bit
.wrap                            ; 32 bits done: back to idle (the closing burst is skipped there)
