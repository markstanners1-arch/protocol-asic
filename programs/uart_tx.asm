; UART transmit, 8N1, LSB first. One bit = 8 engine ticks, so clkdiv sets the baud:
;   baud = f_clk / (8 * (clkdiv + 1))
; Config: out_base = set_base = side_base = TX pin, out_count = set_count = 1, out_right = 1.
.side_set 1 opt
    set    pindirs, 1   side 1          ; drive the TX pin, idle high
.wrap_target
    pull   block        side 1 [7]      ; wait for a byte; line high; this is also the stop bit
    set    x, 7         side 0 [7]      ; start bit: low for 8 ticks; 8 data bits to go
bitloop:
    out    pins, 1                      ; next data bit                (1 tick)
    jmp    x--, bitloop        [6]      ; loop                         (7 ticks) -> 8 per bit
.wrap
