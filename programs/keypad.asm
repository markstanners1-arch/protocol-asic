; 4x4 matrix keypad scanner (4 Nov 2026). Columns = engine pins 4-7, rows = engine pins 16-19 with pull-ups.
; One column at a time is pulled low (open drain: its direction bit set, level 0, the other three released, so two
; keys on one row can never short two driven columns together); the four rows are read, pressed = low.
; After the four columns the ISR holds the 16-key map: column 0's rows in bits 15:12 ... column 3's in 3:0,
; so key (row r, column c) is bit 4*(3-c)+r. The map is inverted (1 = pressed) and compared with the last one
; pushed; on any change the new map is pushed (noblock: a map is self-healing, the next change brings the lot)
; and scanning pauses 1024 ticks for the contacts to stop bouncing. Nothing is pushed while nothing changes.
; Tick = 20 us (clkdiv 239 at 12 MHz, 999 at 50 MHz): a scan is 14 ticks (280 us), the pause about 20.5 ms.
; Config: set_base = 4, set_count = 4 (columns); in_base = 16 (rows); in_right = 0; no side-set, no out pins.
.wrap_target
scan:
    set    pindirs, 1  [1]       ; column 0 low, the rest released; one tick to settle
    in     pins, 4               ; its four rows
    set    pindirs, 2  [1]
    in     pins, 4
    set    pindirs, 4  [1]
    in     pins, 4
    set    pindirs, 8  [1]
    in     pins, 4
    mov    x, ~isr               ; 1 = pressed
    jmp    x!=y, changed
.wrap                            ; same as last time: scan again
changed:
    mov    y, x                  ; remember it
    mov    isr, x
    push   noblock               ; tell the host
    set    x, 31
pause:
    jmp    x--, pause  [31]      ; 32 x 32 ticks of debounce
    jmp    scan
