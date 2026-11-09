"""Model HD44780 character display (LCD 1602), 4-bit wiring (D4-D7), write only, clocked with the engine.

clock(rs, e, d) is called every system clock with the levels of RS, E and D4-D7 (a 4-bit number). The display takes a
nibble on each falling edge of E. Timing is checked against the datasheet's slow-supply (2.7-4.5 V) limits, the
worst case for a display run at 3.3 V logic; every breach is logged in .errors:
  E high 450 ns or more; E cycle (rise to rise) 1000 ns or more; RS set 60 ns before E rises and held 20 ns after it
  falls; D4-D7 set 195 ns before E falls and held 10 ns after
  no write while the display is busy: 4.1 ms after the first power-on function set, 100 us after the second, 2.2 ms
  after clear or home (1.52 ms at 270 kHz, allowing for a slow oscillator), 50 us after anything else (37 us nominal)
  no write in the first 40 ms after power-on (powered_ns: when the supply came up, in ns, relative to clock 0)
Interface: 8-bit after power-on, so each nibble is a whole instruction (low data lines read 0) until a function set
with DL = 0; then pairs of nibbles, high first. Instructions: clear, home, entry mode, display control, shift,
function set, CGRAM and DDRAM address. DDRAM: line 1 at 0x00-0x27, line 2 at 0x40-0x67; the screen shows 16 of each.
"""

BUSY_NS = {"first": 4_100_000, "second": 100_000, "slow": 2_200_000, "fast": 50_000}


class HD44780:
    def __init__(self, clk_hz, powered_ns=0.0):
        self.ns = 1e9 / clk_hz
        self.t = 0
        self.powered = powered_ns
        self.errors = []
        self.last_e = 0
        self.e_rise = None
        self.prev_rise = None
        self.e_fall = None
        self.rs, self.d = 0, 0
        self.rs_change, self.d_change = -1e18, -1e18
        self.busy_until = -1e18
        self.bits8 = True                 # 8-bit interface until a function set with DL = 0
        self.half = None                  # high nibble waiting for its low half (4-bit mode)
        self.fsets = 0                    # function sets seen while in 8-bit mode
        self.lines2, self.font = False, 0
        self.on, self.cursor, self.blink = False, False, False
        self.inc, self.shift = True, False
        self.addr, self.cgram = 0, False
        self.ddram = [0x20] * 0x80
        self.log = []                     # (rs, byte) of every instruction or character taken
        self.min = {"e_high": 1e18, "e_cycle": 1e18, "rs_setup": 1e18, "d_setup": 1e18, "hold": 1e18}

    def _err(self, msg):
        if len(self.errors) < 50:
            self.errors.append("%.3f us: %s" % (self.now / 1000, msg))

    @property
    def now(self):
        return self.t * self.ns

    def clock(self, rs, e, d):
        now = self.now
        if rs != self.rs:
            if self.e_fall is not None and now - self.e_fall < 20 and not self.last_e:
                self._err("RS changed %.0f ns after E fell (hold 20 ns)" % (now - self.e_fall))
            if self.e_fall is not None and not self.last_e:
                self.min["hold"] = min(self.min["hold"], now - self.e_fall)
            self.rs, self.rs_change = rs, now
        if d != self.d:
            if self.e_fall is not None and now - self.e_fall < 10 and not self.last_e:
                self._err("D4-D7 changed %.0f ns after E fell (hold 10 ns)" % (now - self.e_fall))
            if self.e_fall is not None and not self.last_e:
                self.min["hold"] = min(self.min["hold"], now - self.e_fall)
            self.d, self.d_change = d, now
        if e and not self.last_e:                         # E rises
            setup = now - self.rs_change
            self.min["rs_setup"] = min(self.min["rs_setup"], setup)
            if setup < 60:
                self._err("RS set %.0f ns before E rose (60 ns)" % setup)
            if self.prev_rise is not None:
                cyc = now - self.prev_rise
                self.min["e_cycle"] = min(self.min["e_cycle"], cyc)
                if cyc < 1000:
                    self._err("E cycle %.0f ns (1000 ns)" % cyc)
            self.prev_rise = self.e_rise = now
        elif self.last_e and not e:                       # E falls: take the nibble
            width = now - self.e_rise
            self.min["e_high"] = min(self.min["e_high"], width)
            if width < 450:
                self._err("E high %.0f ns (450 ns)" % width)
            setup = now - self.d_change
            self.min["d_setup"] = min(self.min["d_setup"], setup)
            if setup < 195:
                self._err("D4-D7 set %.0f ns before E fell (195 ns)" % setup)
            self.e_fall = now
            self._nibble(self.rs, self.d)
        self.last_e = e
        self.t += 1

    def _nibble(self, rs, nib):
        now = self.now
        if now - self.powered < 40_000_000:
            self._err("write %.2f ms after power-on (40 ms)" % ((now - self.powered) / 1e6))
        if self.bits8:
            self._take(rs, nib << 4)
            return
        if self.half is None:
            if now < self.busy_until:
                self._err("written while busy (%.1f us early)" % ((self.busy_until - now) / 1000))
            self.half = (rs, nib)
            return
        hrs, hi = self.half
        self.half = None
        if hrs != rs:
            self._err("RS changed between the two halves of a byte")
        self._take(rs, hi << 4 | nib, check_busy=False)

    def _take(self, rs, b, check_busy=True):
        now = self.now
        if check_busy and now < self.busy_until:
            self._err("written while busy (%.1f us early)" % ((self.busy_until - now) / 1000))
        self.log.append((rs, b))
        busy = "fast"
        if rs:
            self._write(b)
        elif b == 0x01:
            self.ddram = [0x20] * 0x80
            self.addr, self.cgram, self.inc = 0, False, True
            busy = "slow"
        elif b & 0xFE == 0x02:
            self.addr, self.cgram = 0, False
            busy = "slow"
        elif b & 0xFC == 0x04:
            self.inc, self.shift = bool(b & 2), bool(b & 1)
        elif b & 0xF8 == 0x08:
            self.on, self.cursor, self.blink = bool(b & 4), bool(b & 2), bool(b & 1)
        elif b & 0xF0 == 0x10:
            pass
        elif b & 0xE0 == 0x20:
            if self.bits8:
                self.fsets += 1
                busy = {1: "first", 2: "second"}.get(self.fsets, "fast")
            self.bits8 = bool(b & 0x10)
            self.lines2, self.font = bool(b & 8), (b >> 2) & 1
        elif b & 0xC0 == 0x40:
            self.addr, self.cgram = b & 0x3F, True
        else:
            self.addr, self.cgram = b & 0x7F, False
        self.busy_until = now + BUSY_NS[busy]

    def _write(self, ch):
        if self.cgram:
            self.addr = (self.addr + (1 if self.inc else -1)) & 0x3F
            return
        self.ddram[self.addr] = ch
        a = self.addr + (1 if self.inc else -1)
        if self.lines2:                                   # 0x27 runs on to 0x40, 0x67 back to 0x00
            if a == 0x28:
                a = 0x40
            elif a == 0x68:
                a = 0x00
            elif a == 0x3F:
                a = 0x27
            elif a == -1:
                a = 0x67
        self.addr = a & 0x7F

    def screen(self):
        """The two visible lines (no display shift)."""
        line = lambda base: "".join(chr(c) for c in self.ddram[base:base + 16])
        return [line(0x00), line(0x40)]
