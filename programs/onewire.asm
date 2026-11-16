; Dallas 1-Wire master (standard speed), one open-drain pin with a 4.7 k pull-up (direction 1 = pull low, 0 = let go;
; the pin's output level stays 0). Proven on a model DS18B20 (model/test_onewire.py) and on a DS18B20 (pico/onewire.py).
; One engine tick = 2 us: clkdiv = f_clk * 2 us - 1 (40 MHz: 79; 50 MHz: 99; 12 MHz: 23).
; The host sends one 16-bit word per action; the low 5 bits are the routine's address (assembler labels):
;   reset:  word = reset                  reset pulse and presence check. Pushes bit 15 = the line seen 70 us after
;                                         the release: 0 = a device answered (presence pulse), 1 = nobody there.
;   xfer:   word = byte << 5 | xfer       eight time slots, LSB first. Each slot sends one bit of the byte and reads
;                                         the line back: to write a byte send it; to read one send 0xFF (every slot
;                                         a 1, which a device may pull to 0). Pushes the eight levels seen in bits
;                                         15:8 (bit 8 first), so the byte on the wire is word >> 8.
; Slot, from the falling edge (t = 0): low 4 us; a 1 releases the line at 4 us, a 0 holds it to 64 us; the line is
; sampled at 12 us (a device's 0 lasts at least 15 us); released at 64 us; next slot at 72 us. Within the standard:
; write-1 low 1-15 us, write-0 low 60-120 us, master sample before 15 us, slot 60-120 us, recovery 1 us or more.
; Reset: low 514 us (480-960), released, sampled 70 us later (a device's presence pulse starts 15-60 us after the
; release and lasts 60-240 us, so it is surely low at 60-75 us), then 514 us more high before the next command.
; Config: set_base = out_base = in_base = the pin, set_count = 1, out_count = 1, out_right = 1, in_right = 1
; (LSB first both ways). No side-set.
    set    pindirs, 0              ; power-up: let go of the line
entry:
    pull   block                   ; next command word from the host
    out    pc, 5                   ; low 5 bits = the routine
xfer:
    mov    osr, ~osr               ; bit levels -> directions: a 1 lets go (direction 0), a 0 pulls low
    set    x, 7                    ; eight slots
slot:
    set    pindirs, 1      [1]     ; t = 0: line low, 4 us
    out    pindirs, 1      [3]     ; t = 4: a 1 lets go, a 0 keeps it low; 8 us
    in     pins, 1         [25]    ; t = 12: sample; hold to t = 64
    set    pindirs, 0      [2]     ; t = 64: let go; 6 us recovery
    jmp    x--, slot               ; t = 70; next slot at 72
    push   block                   ; the eight levels seen, bits 15:8
    jmp    entry
reset:
    set    x, 7
    set    pindirs, 1              ; line low
reset_low:
    jmp    x--, reset_low  [31]    ; 8 x 64 us: low 514 us in all
    set    pindirs, 0      [31]    ; let go; 64 us
    mov    y, y            [2]     ; 6 us more (no-op)
    in     pins, 1                 ; t = 70 us after the release: presence?
    set    x, 7
reset_high:
    jmp    x--, reset_high [31]    ; 512 us before the next command (presence and recovery over)
    push   block                   ; bit 15 = 0 if a device answered
    jmp    entry
