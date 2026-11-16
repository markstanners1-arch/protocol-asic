"""Model DS18B20 (Dallas 1-Wire temperature sensor), worst case on the master's timing, clocked with the engine.

clock(line) is called every system clock with the bus level (0 or 1) and returns True while the device pulls the
line low. Times are taken from the clock count, so the model works at any clock rate.
  - reset: the line low for at least 480 us; the presence pulse then starts 30 us after the release and lasts 120 us
  - the device's 0 in a read slot lasts exactly 15 us from the master's falling edge (the minimum it guarantees),
    so a master that samples late reads a 1
  - a written bit is sampled at 15 us and again at 60 us after the falling edge (the ends of the window a real device
    may sample in); if the two differ the bit is ambiguous and is logged in .errors
ROM commands: 0x33 read ROM, 0x55 match ROM, 0xCC skip ROM. Functions: 0x44 convert T (busy for conv_us: read
slots give 0 until done, then 1), 0xBE read scratchpad (9 bytes, CRC last), 0x4E write scratchpad (TH, TL, config).
The scratchpad holds 85.0 C (0x0550) until the first conversion, as the real part does at power-up.
"""


def crc8(data):
    """Dallas/Maxim CRC-8 (x^8 + x^5 + x^4 + 1, LSB first, initial 0)."""
    c = 0
    for b in data:
        for _ in range(8):
            mix = (c ^ b) & 1
            c >>= 1
            if mix:
                c ^= 0x8C
            b >>= 1
    return c


def make_rom(serial):
    """Family 0x28, 48-bit serial, CRC-8 of the first seven bytes."""
    body = [0x28] + [(serial >> (8 * i)) & 0xFF for i in range(6)]
    return body + [crc8(body)]


class DS18B20:
    def __init__(self, clk_hz, serial=0x0000_1A2B_3C4D, temp_c=23.5625, conv_us=5000):
        self.us = 1e6 / clk_hz              # microseconds per clock
        self.rom = make_rom(serial)
        self.temp_c = temp_c
        self.conv_us = conv_us
        self.th, self.tl, self.cfg = 0x4B, 0x46, 0x7F
        self.raw = 0x0550                   # power-up value
        self.t = 0                          # clock count
        self.last = 1
        self.fall = None                    # time of the last falling edge (us)
        self.presence = None                # (start, end) of a presence pulse we owe (us)
        self.hold_until = -1.0              # pulling low until this time (us), for a 0 in a read slot
        self.samples = []                   # pending samples for the slot being written: [time, ...]
        self.slot_bits = []                 # levels taken at those times
        self.state = "idle"
        self.rx_bits, self.rx_byte, self.rx_count = 0, 0, 0
        self.tx = []                        # bits still to send, LSB first
        self.busy_until = None
        self.errors = []
        self.log = []                       # bytes received after each reset
        self.resets = 0

    # ---- protocol
    def _expect(self, state, nbytes=1):
        self.state, self.rx_byte, self.rx_bits, self.rx_count = state, 0, 0, nbytes

    def _send(self, data):
        self.state = "send"
        self.tx = [(b >> i) & 1 for b in data for i in range(8)]

    def _scratchpad(self):
        sp = [self.raw & 0xFF, self.raw >> 8, self.th, self.tl, self.cfg, 0xFF, 0x0C, 0x10]
        return sp + [crc8(sp)]

    def _byte_in(self, b):
        self.log.append(b)
        st = self.state
        if st == "rom":
            if b == 0x33:
                self._send(self.rom)
            elif b == 0xCC:
                self._expect("func")
            elif b == 0x55:
                self._expect("match", 8)
                self.match = []
            else:
                self.state = "idle"
        elif st == "match":
            self.match.append(b)
            if len(self.match) == 8:
                if self.match == self.rom:
                    self._expect("func")
                else:
                    self.state = "idle"           # not us: silent until the next reset
        elif st == "func":
            if b == 0x44:
                self.busy_until = self.now() + self.conv_us
                self.state = "convert"
            elif b == 0xBE:
                self._send(self._scratchpad())
            elif b == 0x4E:
                self._expect("write", 3)
                self.wbuf = []
            else:
                self.state = "idle"
        elif st == "write":
            self.wbuf.append(b)
            if len(self.wbuf) == 3:
                self.th, self.tl, self.cfg = self.wbuf
                self.state = "idle"

    def _raw_from_temp(self):
        return int(round(self.temp_c * 16)) & 0xFFFF

    def now(self):
        return self.t * self.us

    # ---- line
    def clock(self, line):
        now = self.now()
        self.t += 1
        if self.busy_until is not None and now >= self.busy_until:
            self.raw = self._raw_from_temp()
            self.busy_until = None
        if line == 0 and self.last == 1:          # falling edge
            self.fall = now
            if self.presence is None:
                self._slot_start(now)
        elif line == 1 and self.last == 0 and self.fall is not None:   # rising edge
            low = now - self.fall
            if low >= 480 and (self.presence is None or now > self.presence[1]):
                self.resets += 1
                self.presence = (now + 30, now + 150)
                self._expect("rom")
                self.tx, self.samples, self.hold_until = [], [], -1.0
        self.last = line
        # write-slot samples
        while self.samples and now >= self.samples[0]:
            self.samples.pop(0)
            self.slot_bits.append(line)
            if not self.samples:
                a, b = self.slot_bits
                if a != b:
                    self.errors.append("ambiguous bit at %.1f us (%d at 15 us, %d at 60 us)" % (now, a, b))
                self._bit_in(a)
        pull = False
        if self.presence is not None:
            if self.presence[0] <= now < self.presence[1]:
                pull = True
            elif now >= self.presence[1]:
                self.presence = None
        if now < self.hold_until:
            pull = True
        return pull

    def _slot_start(self, now):
        if self.state in ("rom", "match", "func", "write"):
            self.samples = [now + 15, now + 60]
            self.slot_bits = []
        elif self.state == "send" and self.tx:
            if self.tx.pop(0) == 0:
                self.hold_until = now + 15
            if not self.tx:
                self.state = "idle"
        elif self.state == "convert":
            if self.busy_until is not None:
                self.hold_until = now + 15            # still converting: a read slot gives 0
            else:
                self.state = "idle"
        # idle: the device ignores slots until the next reset

    def _bit_in(self, bit):
        self.rx_byte |= bit << self.rx_bits
        self.rx_bits += 1
        if self.rx_bits == 8:
            b = self.rx_byte
            self.rx_byte, self.rx_bits = 0, 0
            self._byte_in(b)
