; 10BASE-T Ethernet transmitter on engine 0's serialiser (ISA v0.3, 5 Nov 2026). 16 words.
; The host pushes one frame as a word count followed by that many words: 4 preamble words (0x5555, 0x5555, 0x5555, 0xD555:
; on the wire 55 55 55 55 55 55 55 D5, each word's low byte first, each byte LSB first), then destination, source, type and
; payload two bytes a word (46 to 1500 payload bytes; the Tiny Tapeout chip's 1024-word buffer holds a full-size frame; the FPGA builds' 64 words, up to about 100 bytes).
; The serialiser waits until the FIFO holds the whole count, sends the words, appends the FCS (CRC-32 over everything after the
; 4 skipped preamble words, complemented) and the TP_IDL (TD+ high 300 ns), then releases the pins to the levels set here.
; Between frames the engine sends a link pulse (TD+ high 100 ns) every 16.4 ms and keeps a 9.6 us gap after each frame.
;
; Settings: out_base = set_base = TD+ (TD- is the next pin up), out_count = set_count = 2, out_right = 1 (LSB first), clkdiv 0.
;   SERCFG 0x107F: enable, Manchester, differential, end marker, CRC append, complemented, CRC watches SER, skip 4 words.
;   CRCPOLY 0xEDB88320, CRCINIT 0xFFFFFFFF.
;   SERDIV: a half-bit is SERDIV + 1 clocks and must be 50 ns: 0 at 20 MHz, 1 at 40 MHz, 2 at 60 MHz.
;   50 MHz cannot divide to 10 Mbit (a half-bit would be 2.5 clocks).
; The delays below are for a 20 MHz chip clock (tick = 50 ns). At 40 MHz: link pulse [3] (4 ticks), poll loop [6]
; (10 ticks a poll), gap "set x, 11" (12 x 32 = 384 ticks).
    set    pindirs, 3            ; TD+ and TD- driven
    set    pins, 0               ; both low: idle, 0 V across the pair
.wrap_target
idle:
    mov    y, ~null              ; 65535 polls of 5 ticks = 16.4 ms (the link pulse interval)
poll:
    mov    osr, status           ; [3:0] = words waiting in the TX FIFO
    out    x, 4
    jmp    !x, nofr
    jmp    frame
nofr:
    jmp    y--, poll     [1]
    set    pins, 1       [1]     ; link pulse: TD+ high for 2 ticks = 100 ns, TD- low
    set    pins, 0
    jmp    idle
frame:
    pull   block                 ; the word count
    mov    ser, osr              ; start the serialiser; it pulls the words itself
    wait   0, ser                ; until the frame, FCS and TP_IDL have gone out
    set    x, 5                  ; interframe gap: 6 loops of 32 ticks = 192 ticks = 9.6 us
gap:
    jmp    x--, gap      [31]
.wrap
