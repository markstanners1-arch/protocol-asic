; I2C bus watcher: pushes every byte seen on the bus with its ACK bit: word[8:1] = the byte, word[0] = ACK (0 = acked).
; Samples SDA on each SCL rising edge, then watches both pins until SCL falls: SDA changing while SCL is high is a
; START (falling) or STOP (rising), and either throws away the partial byte and resyncs, so repeated STARTs and
; STOPs (each has an SCL rise with no data in it) never put the byte count out of step. A SDA change that is
; really the next data bit after a very short hold time is told apart by looking at SCL again.
; Config: in_base = SCL's pin (SDA is the next one up), jmp_pin = SDA's pin, out_right = 1, in_right = 0 (MSB first).
    wait   1, rel 0          ; SCL idle high first: the synchroniser shows every pin low for 2 clocks after reset
sync:
    mov    isr, null         ; empty the byte
    set    x, 8              ; 9 clocks: 8 data bits and the ACK
bit:
    wait   0, rel 0          ; SCL low
    wait   1, rel 0          ; SCL rising edge: the bit is valid now
    jmp    pin, got1
    in     null, 1           ; SDA low: a 0 bit
poll0:
    mov    osr, pins         ; snapshot SCL (bit 0) and SDA (bit 1)
    out    y, 1              ; y = SCL
    jmp    !y, next          ; SCL fell: bit done
    jmp    pin, maybe_stop   ; SDA rose while SCL high?
    jmp    poll0
maybe_stop:
    mov    osr, pins
    out    y, 1
    jmp    !y, next          ; no: SCL had just fallen, SDA moved on to the next bit
    jmp    sync              ; yes: STOP
got1:
    set    y, 1
    in     y, 1              ; SDA high: a 1 bit
poll1:
    mov    osr, pins
    out    y, 1
    jmp    !y, next
    jmp    pin, poll1        ; SDA still high: keep watching
    mov    osr, pins         ; SDA fell while SCL high?
    out    y, 1
    jmp    !y, next          ; no: SCL had just fallen
    jmp    sync              ; yes: START (or repeated START)
next:
    jmp    x--, bit
    push   noblock           ; the byte and its ACK (dropped if the host is 4 behind)
    jmp    sync
