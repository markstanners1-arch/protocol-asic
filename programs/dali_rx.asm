; DALI backward frame receiver (4 Nov 2026): the gear's 8-bit answer to a query, read from the bus voltage on an input pin
; (bus high = 1, bus shorted = 0, through a divider: no inversion). Same coding as the forward frame: a start bit (a 1: low
; then high), 8 data bits MSB first, then idle high. Tick = an eighth of a bit, 104.17 us, the same clkdiv as dali_tx
; (1249 at 12 MHz, 5207 at 50 MHz).
; How the host uses it: push the listening window in ticks (96 = 10 ms) to ARM the engine, then push the forward frame to the
; dali_tx engine. The armed engine waits for the forward frame to start (a falling edge), then for the bus to be quiet
; (high at 8 polls 2 ticks apart, 1.5 to 1.7 ms: a Manchester frame is never high for more than one bit, 0.83 ms), which is
; the end of the forward frame; then it listens for the answer's falling edge for the window (the standard's answer comes
; 2.9 to 9.2 ms after the forward frame). One word comes back per arming:
;     0x100 | byte   a good frame (the start bit sits in bit 8, like uart_rx's stop flag)
;     0x000          no answer: nothing started in the window (a "no" to a yes/no query, or nobody at that address)
;     0x200 | part   framing error: a mid-bit transition did not come when due. part = a 1 (the start bit) followed by the
;                    bits that were read before the fault, so its top set bit says how far the frame got (0x201 = none)
; Arm BEFORE the forward frame (or within 1 ms after its push): armed after the forward frame has gone, the engine takes the
; answer itself as the frame to skip and reports 0x000. Stopping the engine cancels an arming.
; Decoding: RESYNC ON EVERY MID-BIT EDGE rather than sampling at fixed quarter points from the start edge, because a gear's
; clock may be 10 % off (the standard's allowance) and over nine bits that drifts most of a half bit, while from one
; mid-bit edge to the next it is under a tick. From the edge seen at tick T (the real edge was within the tick before):
; the bit boundary, where the bus changes only if the next bit repeats this one, is at T+3.6 to T+4.4; the next mid-bit
; edge at T+7.2 to T+8.8. So the first half of the next bit is sampled at T+5 (jmp pin: high means a 0 is coming, low a 1),
; then the engine waits for the opposite level, the mid-bit edge, with a timeout at T+10 (0.6 of a bit late: a missing
; edge is a framing error before the following bit's boundary could be mistaken for it). The level just after the edge
; is the bit. Both paths take the same ticks (the 0 path's delay of 1 matches the 1 path's extra jump).
; Config: in_base = jmp_pin = the RX pin, in_right = 0 (MSB first), fault_addr = fault (label; the Pico tables carry it);
; no outputs, no side-set. 26 words.
.wrap_target
idle:
    pull   block                 ; armed: the OSR holds the window
    wait   0, rel 0              ; the forward frame starts (the bus is idle high when the host arms)
quiet:
    set    x, 7                  ; the frame has ended when the bus is high at 8 polls 2 ticks apart
poll:
    jmp    pin, high
    jmp    quiet                 ; low: still in the frame, count again
high:
    jmp    x--, poll             ; falls through with x = 0xFFFF (x-- wraps), used below
    out    y, 16                 ; the window, in ticks
    wait   0, rel 0, timeout     ; the answer's start bit, bus shorted; or nothing within the window: fault with the ISR empty
    in     x, 1                  ; the start bit, a 1 (x's low bit), into the ISR: from here a fault is a framing error
    set    y, 4                  ; the start bit's rising edge is due 4 ticks after its falling edge, seen a tick late at most
    wait   1, rel 0, timeout     ; mid-bit edge of the start bit, seen at tick T
    set    x, 7         [2]      ; 8 data bits; T+1 and two idle ticks
bit:
    set    y, 4                  ; T+4
    jmp    pin, zero             ; T+5: first half of the next bit; high means its mid-bit edge falls, so it is a 0
    wait   1, rel 0, timeout     ; a 1: the rising edge, seen at the new T; from T+6 to T+10, else fault
    jmp    got                   ; T+1
zero:
    wait   0, rel 0, timeout [1] ; a 0: the falling edge; the delay matches the jump on the other path
got:
    in     pins, 1               ; T+2: the level after the edge is the bit (the boundary cannot come before T+2.6)
    jmp    x--, bit              ; T+3
done:
    push   noblock               ; 0x100 | byte, or 0x000, or 0x200 | part
.wrap
fault:
    mov    x, isr                ; what was read before the fault
    jmp    !x, done              ; nothing at all: no answer, push the empty ISR as 0x000
    set    y, 2
    mov    isr, y                ; 0x200 ...
    in     x, 8                  ; ... | the start bit and the bits so far
    jmp    done
