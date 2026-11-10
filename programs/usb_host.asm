; Low-speed USB host turnaround on engine 0 (USB mode: private/usb_ls.md; model only so far, model/test_usb.py).
; The serialiser sends each packet (NRZI, stuffing, EOP, and the pin directions while it sends); the receiver listens
; from our EOP's J and judges the reply; this program decides when to send, waits for the reply, and sends the ACK the
; host queued if the reply was a good DATA packet (status bit 10), 2 to 7.5 bit times after it. It also sends a
; keep-alive (an EOP alone) after about 0.8 ms with nothing to send.
;
; Settings: clkdiv 0 (40 MHz), out_base 0 (D+; D- on pin 1), RXCFG pin 0, out_right = in_right = 1, fault_addr = drop,
; SERCFG enable + full duplex, USBCFG [0], SERDIV 12, SERFRAC 85, RXGAP 27.
; Host words: first the timeout constant (8000: 200 us reply timeout, about 0.8 ms between keep-alives), then per
; transaction a job word ([7:0] bytes with SYNC, [14] a reply is expected and an ACK job follows, [15] keep-alive),
; the packet's words, and after a [14] job the ACK job 0x0002 and its word 0xD280 (SYNC, ACK).
    pull   block               ; once: the timeout constant
    mov    isr, osr            ; kept in the ISR
.wrap_target
top:
    wait   0, ser              ; the last packet or keep-alive has gone
    mov    y, isr
poll:
    mov    osr, status
    out    x, 4                ; words waiting in the transmit ring
    jmp    !x, idle
    pull   block               ; a job word
    mov    ser, osr            ; send: the receiver listens from the EOP's J
    out    null, 14
    out    x, 1                ; x = a reply is expected
    wait   0, ser      [31]    ; gone, then 2 bit times before anything else (a SETUP's DATA0 follows)
    jmp    !x, top     [15]
    mov    y, isr              ; reply timeout
    wait   1, pin 25, timeout  ; the reply's EOP (WAIT 25: frame ready); no reply: to drop
    mov    osr, status
    out    null, 10
    out    x, 1                ; status [10]: a good DATA packet
    jmp    !x, drop
    mov    y, y        [31]    ; the ACK 2 to 7.5 bit times after the reply's EOP
    mov    y, y        [15]
    pull   block               ; the ACK job word
    mov    ser, osr            ; SYNC + ACK, EOP
    jmp    top
drop:
    pull   block               ; the ACK job, not wanted (a handshake, a bad packet, or no reply)
    pull   block               ; and its word
    jmp    top
idle:
    jmp    y--, poll
    mov    ser, ~null          ; keep-alive: 0xFFFF has [15] set
.wrap
