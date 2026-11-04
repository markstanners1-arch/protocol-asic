; UART receive, 8N1, LSB first (4 Nov 2026). One bit = 8 engine ticks, the same clkdiv as uart_tx:
;   baud = f_clk / (8 * (clkdiv + 1))      (12 MHz, 115200: clkdiv 12; 9600: 155.  50 MHz, 115200: 53)
; Each byte is pushed as one word: bits 7:0 the data, bit 8 the stop bit (1 = good frame, 0 = framing error
; or break), bits 15:9 zero. The host reads bit 8 before trusting the byte. After a bad stop bit the engine
; waits for the line to be idle again before listening, so a break gives one 0x0000 and nothing more.
; Config: in_base = jmp_pin = the RX pin, in_right = 1 (LSB first). No outputs, no side-set. Y is kept at 1.
; Timing, in ticks from t0 = the tick the start edge is seen (up to a tick after the real edge): the start bit is
; checked again at t0+3 and a glitch shorter than that is thrown away; the data bits are sampled at t0+11, +19 ...
; +67 (a tick before the middle of each bit, which with the late t0 lands in the middle) and the stop bit at
; t0+75; the engine is waiting for the next edge again at t0+78, so a sender can run bytes back to back up to
; 2.5 % fast (its next edge is at t0+80 at the nominal rate). With a gap between bytes, 4 % either way decodes.
    set    y, 1                ; once: the value shifted in above the data as a good stop bit
start:
    wait   1, pin 0            ; see the line idle first (the synchroniser resets low: never trust a low after reset)
.wrap_target
    wait   0, pin 0            ; start edge                                                      t0
    set    x, 7        [1]     ; 8 data bits to read                                              t0+1, then 1 tick
    jmp    pin, start  [7]     ; still low in the start bit? else a glitch: back to waiting      t0+3, then 7 ticks
bitloop:
    in     pins, 1             ; sample the bit                                                  t0+11, +19 ... +67
    jmp    x--, bitloop [6]    ; 8 ticks per bit; the last pass delays 6 too, so the stop bit is read at t0+75
    jmp    pin, good           ; the stop bit                                                    t0+75
    in     null, 8             ; framing error: bit 8 = 0 above the data
    push   noblock
    jmp    start               ; and wait for the line to come back up before listening again
good:
    in     y, 8                ; bit 8 = 1 above the data (the low 8 bits of y = 0x01)            t0+76
    push   noblock             ; the host reads it; a full FIFO loses the byte rather than stalling the line   t0+77
.wrap                          ; straight back to the start-edge wait: the stop bit is still high, no need to wait for it
