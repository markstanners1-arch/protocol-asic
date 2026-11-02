; SPI master, mode 0 (SCK idles low, MOSI changes on the falling edge, MISO is sampled on the rising edge), MSB first.
; SCK = engine pin 0 (side-set), MOSI = pin 1 (out), MISO = pin 2 (in), CS = pin 3 (set), all driven except MISO.
; The host sends one 16-bit command word per action; the top 5 bits are the routine's address (assembler labels):
;   select:    word = select << 11                     CS low
;   xfer:      word = xfer << 11 | byte << 3            send a byte and push the byte that came back
;   deselect:  word = deselect << 11                   CS high
; One bit = 6 engine ticks (SCK low 3, high 3), so SCK = f_clk / (6 * (clkdiv + 1)); e.g. 50 MHz, clkdiv 7 -> 1.04 MHz.
; Config: side_base = 0, side_count = 1; set_base = 0, set_count = 4; out_base = 1, out_count = 1; in_base = 2;
;         out_right = in_right = 0 (MSB first).
.side_set 1 opt
    set    pins, 8       side 0      ; idle levels first: CS high, SCK low, MOSI low (so CS never dips when driven)
    set    pindirs, 11               ; then drive SCK, MOSI and CS (bits 0, 1, 3); MISO (bit 2) stays an input
entry:
    pull   block                     ; next command word from the host
    out    pc, 5                     ; top 5 bits = the routine
xfer:
    set    x, 7
xfer_bit:
    out    pins, 1       side 0 [1]  ; MOSI = next bit while SCK is low
    in     pins, 1       side 1 [2]  ; SCK high: sample MISO
    jmp    x--, xfer_bit side 0      ; SCK low
    push   block                     ; the byte that came back
    jmp    entry
select:
    set    pins, 0                   ; CS low (SCK and MOSI low too)
    jmp    entry
deselect:
    set    pins, 8                   ; CS high
    jmp    entry
