"""Clock-by-clock model of one engine, written from docs/isa.md (v0.3).

This is the reference ("the calculated values"): the Verilog engine must match it
on every system clock. Keep it plain and literal; speed doesn't matter, clarity does.

    eng = Engine(program, Config(...))
    popped = eng.clock(pins_in, push=word_or_None, pop=False)   # one system clock
    eng.out_val, eng.out_dir    # the program's pin levels and directions after this clock
    eng.pins_out                # the levels on the pins: out_val, with the serialiser's pins while it owns them
  Convenience: eng.tx_put(word) / eng.rx_get() queue a host push / pop for the next clock.
  Host FIFO timing follows docs/isa.md: decided from the state at the start of the clock.

Engine 0 (Config.ser = True) carries the bit-cell serialiser and a 64-word TX FIFO; every engine carries a
32-bit CRC unit (docs/isa.md, "Serialiser" and "CRC unit"). The 64-word TX FIFO is a one-port memory behind a head
register (docs/isa.md, "Host and FIFO timing"): tx_hv says the head word, txf[0], is ready for PULL and the serialiser.
"""
from collections import deque
from dataclasses import dataclass

M16 = 0xFFFF
M32 = 0xFFFFFFFF
FIFO_DEPTH = 4                  # RX FIFO, and the TX FIFO of an engine without the serialiser
SER_FIFO_DEPTH = 64             # TX FIFO of the engine with the serialiser
SER_WAIT_INDEX = 24             # WAIT index that reads "serialiser busy"
END_HALF_BITS = 6               # end-of-frame marker: the line held high for this many half-bits


@dataclass
class Config:
    clkdiv: int = 0
    start: int = 0
    wrap_bottom: int = 0
    wrap_top: int = 31
    out_base: int = 0
    out_count: int = 1
    set_base: int = 0
    set_count: int = 1
    side_base: int = 0
    side_count: int = 0
    side_opt: bool = False
    side_dir: bool = False       # side-set writes directions (open drain) instead of levels
    in_base: int = 0
    jmp_pin: int = 0
    out_right: bool = True
    in_right: bool = True
    fault_addr: int = 0
    # v0.3: the serialiser (engine 0 only: ser = True) and the CRC unit (every engine)
    ser: bool = False            # this engine has the serialiser and the deep TX FIFO
    ser_en: bool = False         # SERCFG[0]: MOV ser starts a frame (else it does nothing)
    manch: bool = False          # SERCFG[1]: Manchester (else NRZ)
    diff: bool = False           # SERCFG[2]: out_base + 1 carries the inverse
    end_marker: bool = False     # SERCFG[3]: line high for 6 half-bits after the last bit
    crc_append: bool = False     # SERCFG[4]: the CRC register follows the data, 32 bits
    crc_cpl: bool = False        # SERCFG[5]: ... complemented
    crc_ser: bool = False        # SERCFG[6]: the CRC watches the serialiser's data bits (else IN bits)
    crc_skip: int = 0            # SERCFG[12:10]: the serialiser's first crc_skip words are not fed to the CRC
    serdiv: int = 0              # half-bit period in clocks, minus 1
    crcpoly: int = 0             # reflected polynomial
    crcinit: int = 0             # start value

    @classmethod
    def for_program(cls, prog, **kw):
        """Take the wrap and side-set settings from an assembled program."""
        return cls(wrap_bottom=prog.wrap_bottom, wrap_top=prog.wrap_top,
                   side_count=prog.side_count, side_opt=prog.side_opt, side_dir=prog.side_dir, **kw)

    @property
    def tx_depth(self):
        return SER_FIFO_DEPTH if self.ser else FIFO_DEPTH

    def sercfg_word(self):
        """SERCFG as the host writes it (docs/host_port.md)."""
        return (int(self.ser_en) | int(self.manch) << 1 | int(self.diff) << 2 | int(self.end_marker) << 3
                | int(self.crc_append) << 4 | int(self.crc_cpl) << 5 | int(self.crc_ser) << 6 | (self.crc_skip & 7) << 10)

    def set_sercfg_word(self, w):
        self.ser_en, self.manch, self.diff, self.end_marker = bool(w & 1), bool(w & 2), bool(w & 4), bool(w & 8)
        self.crc_append, self.crc_cpl, self.crc_ser, self.crc_skip = bool(w & 16), bool(w & 32), bool(w & 64), (w >> 10) & 7
        return self


# Ada-style range declarations: every register and its legal range.
# After every clock, check_ranges() stops the model dead if anything has strayed
# (the Python equivalent of Ada's "type Word is mod 2**16" and "range 0 .. 16").
RANGES = {
    "pc": (0, 31), "x": (0, M16), "y": (0, M16), "osr": (0, M16), "isr": (0, M16),
    "osr_count": (0, 16), "isr_count": (0, 16), "delay": (0, 31), "sw": (0, M16),
    "div": (0, M16), "out_val": (0, M32), "out_dir": (0, M32), "sync1": (0, M32), "sync2": (0, M32),
    "crc": (0, M32), "ser_phase": (0, 3), "ser_words": (0, M16), "ser_sh": (0, M16), "ser_bit": (0, 31),
    "ser_half": (0, 1), "ser_div": (0, M16), "ser_skip": (0, 7),
}
CHECK_RANGES = True

# serialiser phases
FILL, DATA, CRC, END = 0, 1, 2, 3


class RangeError(Exception):
    pass


def _bitrev16(v):
    return int(f"{v & M16:016b}"[::-1], 2)


def crc_step(crc, poly, bit):
    """One bit through the right-shifting (reflected) CRC: docs/isa.md, CRC unit."""
    if (crc ^ bit) & 1:
        return ((crc >> 1) ^ poly) & M32
    return crc >> 1


class Engine:
    def __init__(self, program, cfg):
        words = program.words if hasattr(program, "words") else list(program)
        self.mem = (list(words) + [0] * 32)[:32]
        self.cfg = cfg
        self.reset()

    def reset(self):
        c = self.cfg
        self.pc = c.start
        self.x = self.y = 0
        self.osr, self.osr_count = 0, 16
        self.isr, self.isr_count = 0, 0
        self.delay = 0
        self.sw, self.sw_run = 0, False
        self.div = 0
        self.out_val = 0
        self.out_dir = 0
        self.txf = deque()
        self.tx_hv = False          # 64-word FIFO: the head register holds txf[0]
        self._tx_ready0 = self._tx_popped = False
        self.rxf = deque()
        self.sync1 = self.sync2 = 0
        self.ticks = 0
        self.stalled = False
        self._push = None
        self._pop = False
        # CRC unit
        self.crc = c.crcinit & M32
        # serialiser
        self.ser_busy = False
        self.ser_under = False
        self.ser_phase = FILL
        self.ser_words = 0
        self.ser_sh = 0
        self.ser_bit = 0
        self.ser_half = 0
        self.ser_div = 0
        self.ser_skip = 0
        self.ser_wskip = False      # the word being sent is one of the crc_skip unwatched words
        # per-clock requests from the instruction to the units
        self._start = None          # MOV ser value
        self._crc_clr = False       # TIME 5 (or a frame start)
        self._crc_in = None         # the IN bit for the CRC (IN mode)
        # coverage counters (for the random tests' report; not state)
        self.events = {"start": 0, "abort": 0, "done": 0, "underrun": 0, "crc_sent": 0, "end_sent": 0,
                       "in_crc": 0, "time_crc": 0, "wait_ser": 0, "pull_busy": 0,
                       "refill_blocked": 0, "pull_not_ready": 0, "under_not_ready": 0}

    # ---- host side ----
    def tx_put(self, word):
        """Queue a host push for the next clock. False if it would be refused."""
        if len(self.txf) >= self.cfg.tx_depth or self._push is not None:
            return False
        self._push = word & M16
        return True

    def rx_get(self):
        """Queue a host pop for the next clock and return the word it will take (None if empty)."""
        if not self.rxf or self._pop:
            return None
        self._pop = True
        return self.rxf[0]

    # ---- pins ----
    def _pin(self, n):
        return (self.sync2 >> (n % 32)) & 1

    def _wait_pin(self, n):
        """What WAIT sees at index n: the pin, except index 24 on the serialiser's engine = serialiser busy."""
        if self.cfg.ser and n % 32 == SER_WAIT_INDEX:
            self.events["wait_ser"] += 1
            return int(self.ser_busy)
        return self._pin(n)

    def _pins_from(self, base, count):
        return sum(self._pin(base + i) << i for i in range(count))

    @staticmethod
    def _write(reg, base, count, data):
        for i in range(count):
            p = (base + i) % 32
            reg = (reg & ~(1 << p)) | (((data >> i) & 1) << p)
        return reg & M32

    # ---- the serialiser's view of the pins ----
    @property
    def ser_own(self):
        """The serialiser owns out_base (and out_base + 1 if differential) while it is shifting."""
        return self.ser_busy and self.ser_phase != FILL

    def ser_line(self):
        """The encoded level the serialiser puts on out_base this clock (meaningful while ser_own)."""
        c = self.cfg
        if self.ser_phase == END:
            return 1
        if self.ser_phase == DATA:
            b = self.ser_sh & 1 if c.out_right else (self.ser_sh >> 15) & 1
        else:                                            # CRC: the register, bit 0 first (right) or bit 31 first
            b = (self.crc >> (self.ser_bit if c.out_right else 31 - self.ser_bit)) & 1
            if c.crc_cpl:
                b ^= 1
        if c.manch:
            return b if self.ser_half else b ^ 1         # first half = the inverse, second half = the bit
        return b

    @property
    def pins_out(self):
        if not self.ser_own:
            return self.out_val
        line = self.ser_line()
        v = self._write(self.out_val, self.cfg.out_base, 1, line)
        if self.cfg.diff:
            v = self._write(v, self.cfg.out_base + 1, 1, line ^ 1)
        return v

    # ---- one system clock ----
    def clock(self, pins_in=0, push=None, pop=False):
        """One system clock. Returns the word the host popped, or None."""
        if self._push is not None:
            push, self._push = self._push, None
        if self._pop:
            pop, self._pop = True, False
        # host requests are judged on the state at the start of the clock
        tx0 = len(self.txf)
        mem_fifo = self.cfg.tx_depth == SER_FIFO_DEPTH
        hv0 = self.tx_hv if mem_fifo else tx0 > 0     # the head word is ready (PULL and the serialiser take it)
        self._tx_ready0, self._tx_popped = hv0, False
        push_ok = push is not None and tx0 < self.cfg.tx_depth
        pop_ok = pop and len(self.rxf) > 0
        popped = self.rxf[0] if pop_ok else None
        self._start, self._crc_clr, self._crc_in = None, False, None
        if self.div == 0:
            self.div = self.cfg.clkdiv
            self._tick()
        else:
            self.div -= 1
        ser_bit = self._ser_clock(tx0, hv0)
        self._crc_clock(ser_bit)
        if mem_fifo:
            # the one memory port: a push writes; else, if the head is empty or taken, the next unread word is read
            unread = tx0 - int(hv0)
            read = not push_ok and (not hv0 or self._tx_popped) and unread > 0
            if push_ok and (not hv0 or self._tx_popped) and unread > 0:
                self.events["refill_blocked"] += 1
            self.tx_hv = True if read else (False if self._tx_popped else hv0)
        if push_ok:
            self.txf.append(push & M16)
        if pop_ok:
            self.rxf.popleft()
        # synchroniser: the engine sees pins as they were 2 clocks ago
        self.sync2, self.sync1 = self.sync1, pins_in & M32
        if CHECK_RANGES:
            self.check_ranges()
        return popped

    def check_ranges(self):
        for name, (lo, hi) in RANGES.items():
            v = getattr(self, name)
            if not (isinstance(v, int) and lo <= v <= hi):
                raise RangeError(f"{name} = {v!r} is outside {lo} .. {hi} (pc {self.pc}, tick {self.ticks})")
        if not (len(self.txf) <= self.cfg.tx_depth and len(self.rxf) <= FIFO_DEPTH):
            raise RangeError(f"FIFO over depth: tx {len(self.txf)} rx {len(self.rxf)}")
        for w in list(self.txf) + list(self.rxf):
            if not 0 <= w <= M16:
                raise RangeError(f"FIFO word {w!r} outside 0 .. 65535")

    # ---- the serialiser: one system clock (docs/isa.md, Serialiser) ----
    def _ser_load(self):
        """Pull the next word of the frame into the shift register and start its first bit. Returns the first bit."""
        c = self.cfg
        self.ser_sh = self.txf.popleft()
        self._tx_popped = True
        self.ser_words -= 1
        self.ser_bit, self.ser_half, self.ser_div, self.ser_phase = 0, 0, c.serdiv, DATA
        self.ser_wskip = self.ser_skip > 0
        if self.ser_skip > 0:
            self.ser_skip -= 1
        return self.ser_sh & 1 if c.out_right else (self.ser_sh >> 15) & 1

    def _ser_clock(self, tx0, hv0):
        """Returns the data bit the serialiser started this clock (for the CRC), or None."""
        c = self.cfg
        if not (c.ser and c.ser_en):
            return None
        if self._start is not None:                      # MOV ser: restart with the new count; 0 stops
            if self._start == 0:
                self.ser_busy, self.ser_phase = False, FILL
                self.events["abort"] += 1
            else:
                self.ser_busy, self.ser_under, self.ser_phase = True, False, FILL
                self.ser_words, self.ser_skip = self._start, c.crc_skip
                self._crc_clr = True
                self.events["start"] += 1
            return None
        if not self.ser_busy:
            return None
        if self.ser_phase == FILL:                       # waiting for the whole frame to be in the FIFO
            if (tx0 >= self.ser_words or tx0 == c.tx_depth) and hv0:
                b = self._ser_load()
                return None if self.ser_wskip else b
            return None
        if self.ser_div != 0:                            # inside a half-bit
            self.ser_div -= 1
            return None
        self.ser_div = c.serdiv                          # a half-bit boundary
        if self.ser_phase == END:
            if self.ser_bit < END_HALF_BITS - 1:
                self.ser_bit += 1
            else:
                self.ser_busy = False
                self.events["done"] += 1
            return None
        if self.ser_half == 0:
            self.ser_half = 1
            return None
        self.ser_half = 0                                # a bit boundary
        if self.ser_phase == DATA:
            if self.ser_bit < 15:
                self.ser_bit += 1
                if c.out_right:
                    self.ser_sh >>= 1
                    b = self.ser_sh & 1
                else:
                    self.ser_sh = (self.ser_sh << 1) & M16
                    b = (self.ser_sh >> 15) & 1
                return None if self.ser_wskip else b
            if self.ser_words > 0:                       # the word is done: the next one
                if hv0:
                    b = self._ser_load()
                    return None if self.ser_wskip else b
                self.ser_busy, self.ser_under = False, True
                self.events["underrun"] += 1
                if tx0:
                    self.events["under_not_ready"] += 1  # words in the FIFO, none in the head yet
            elif c.crc_append:
                self.ser_phase, self.ser_bit = CRC, 0
                self.events["crc_sent"] += 1
            elif c.end_marker:
                self.ser_phase, self.ser_bit = END, 0
                self.events["end_sent"] += 1
            else:
                self.ser_busy = False
                self.events["done"] += 1
            return None
        # CRC phase
        if self.ser_bit < 31:
            self.ser_bit += 1
        elif c.end_marker:
            self.ser_phase, self.ser_bit = END, 0
            self.events["end_sent"] += 1
        else:
            self.ser_busy = False
            self.events["done"] += 1
        return None

    # ---- the CRC unit: one system clock (docs/isa.md, CRC unit) ----
    def _crc_clock(self, ser_bit):
        c = self.cfg
        if self._crc_clr:
            self.crc = c.crcinit & M32
        elif c.ser and c.crc_ser:
            if ser_bit is not None:
                self.crc = crc_step(self.crc, c.crcpoly, ser_bit)
        elif self._crc_in is not None:
            self.crc = crc_step(self.crc, c.crcpoly, self._crc_in)

    def _tick(self):
        self.ticks += 1
        if self.sw_run:
            self.sw = min(M16, self.sw + 1)
        if self.delay > 0:
            self.delay -= 1
            return
        self._execute(self.mem[self.pc])

    def _next_pc(self):
        return self.cfg.wrap_bottom if self.pc == self.cfg.wrap_top else (self.pc + 1) % 32

    def _execute(self, w):
        c = self.cfg
        op = (w >> 13) & 7
        mid = (w >> 8) & 31
        a = w & 0xFF

        # split the middle field: [enable] [side value] [delay]
        dbits = 5 - c.side_count - (1 if c.side_opt else 0)
        delay = mid & ((1 << dbits) - 1)
        side_val = (mid >> dbits) & ((1 << c.side_count) - 1)
        side_en = c.side_count > 0 and (not c.side_opt or (mid >> 4) & 1)

        jump = None        # new pc if this instruction jumps
        stall = False

        if op == 0:                                    # JMP
            cond, addr = a >> 5, a & 31
            if cond == 0:   take = True
            elif cond == 1: take = self.x == 0
            elif cond == 2: take = self.x != 0; self.x = (self.x - 1) & M16
            elif cond == 3: take = self.y == 0
            elif cond == 4: take = self.y != 0; self.y = (self.y - 1) & M16
            elif cond == 5: take = self.x != self.y
            elif cond == 6: take = self._pin(c.jmp_pin) == 1
            else:           take = self.osr_count < 16
            if take:
                jump = addr

        elif op == 1:                                  # WAIT
            level, timeout, rel, idx = a >> 7, (a >> 6) & 1, (a >> 5) & 1, a & 31
            pin = (c.in_base + idx) if rel else idx
            if self._wait_pin(pin) != level:
                if timeout and self.y == 0:
                    jump = c.fault_addr
                else:
                    if timeout:
                        self.y = (self.y - 1) & M16
                    stall = True

        elif op == 2:                                  # IN
            src, n = a >> 5, (a & 15) or 16
            data = {0: lambda: self._pins_from(c.in_base, 16), 1: lambda: self.x, 2: lambda: self.y,
                    3: lambda: 0, 4: lambda: self.isr, 5: lambda: self.osr,
                    6: lambda: self.sw, 7: lambda: self.crc & M16}[src]()
            if src == 7:
                self.events["in_crc"] += 1
            data &= (1 << n) - 1
            if c.in_right:
                self.isr = ((self.isr >> n) | (data << (16 - n))) & M16 if n < 16 else data
            else:
                self.isr = ((self.isr << n) | data) & M16
            self.isr_count = min(16, self.isr_count + n)
            # the CRC unit (IN mode) takes the first bit shifted in: bit 0 (right) or bit n-1 (left)
            self._crc_in = data & 1 if c.in_right else (data >> (n - 1)) & 1

        elif op == 3:                                  # OUT
            dst, n = a >> 5, (a & 15) or 16
            mask = (1 << n) - 1
            if c.out_right:
                data = self.osr & mask
                self.osr = (self.osr >> n) & M16 if n < 16 else 0
            else:
                data = (self.osr >> (16 - n)) & mask
                self.osr = (self.osr << n) & M16
            self.osr_count = min(16, self.osr_count + n)
            if dst == 0:   self.out_val = self._write(self.out_val, c.out_base, n, data)
            elif dst == 1: self.x = data
            elif dst == 2: self.y = data
            elif dst == 4: self.out_dir = self._write(self.out_dir, c.out_base, n, data)
            elif dst == 5: jump = data & 31
            elif dst == 6: self.isr, self.isr_count = data, n

        elif op == 4:                                  # PUSH / PULL
            is_pull, cond, block = a >> 7, (a >> 6) & 1, (a >> 5) & 1
            if not is_pull:
                if cond and self.isr_count < 16:
                    pass
                elif len(self.rxf) >= FIFO_DEPTH:
                    stall = bool(block)
                else:
                    self.rxf.append(self.isr)
                    self.isr, self.isr_count = 0, 0
            else:
                if self.ser_busy:
                    self.events["pull_busy"] += 1
                if cond and self.osr_count < 16:
                    pass
                elif not self._tx_ready0 or self.ser_busy:   # while the serialiser is busy the FIFO is its own: PULL finds it empty
                    if self.txf and not self.ser_busy:
                        self.events["pull_not_ready"] += 1
                    if block:
                        stall = True
                    else:
                        self.osr, self.osr_count = self.x, 0
                else:
                    self.osr, self.osr_count = self.txf.popleft(), 0
                    self._tx_popped = True

        elif op == 5:                                  # MOV
            dst, mop, src = a >> 5, (a >> 3) & 3, a & 7
            v = {0: lambda: self._pins_from(c.in_base, 16), 1: lambda: self.x, 2: lambda: self.y,
                 3: lambda: 0, 4: lambda: self.sw,
                 5: lambda: (min(len(self.txf), 15) | ((len(self.rxf) & 15) << 4)
                             | int(self.ser_busy) << 8 | int(self.ser_under) << 9),
                 6: lambda: self.isr, 7: lambda: self.osr}[src]()
            if mop == 1:   v = ~v & M16
            elif mop == 2: v = _bitrev16(v)
            if dst == 0:   self.out_val = self._write(self.out_val, c.out_base, c.out_count, v)
            elif dst == 1: self.x = v
            elif dst == 2: self.y = v
            elif dst == 3: self._start = v             # mov ser: start a frame of v words (0 stops); engine 0 only
            elif dst == 5: jump = v & 31
            elif dst == 6: self.isr, self.isr_count = v, 0
            elif dst == 7: self.osr, self.osr_count = v, 0

        elif op == 6:                                  # SET
            dst, v = a >> 5, a & 31
            if dst == 0:   self.out_val = self._write(self.out_val, c.set_base, c.set_count, v)
            elif dst == 1: self.x = v
            elif dst == 2: self.y = v
            elif dst == 4: self.out_dir = self._write(self.out_dir, c.set_base, c.set_count, v)

        else:                                          # TIME
            act = a >> 5
            if act == 0:   self.sw, self.sw_run = 0, True
            elif act == 1: self.sw_run = False
            elif act == 2: self.x = self.sw
            elif act == 3: self.y = self.sw
            elif act == 4: self.isr, self.isr_count = self.sw, 16
            elif act == 5:
                self._crc_clr = True                   # time crc reset
                self.events["time_crc"] += 1

        # side-set happens on every executed step, stalled or not, and wins over the instruction
        if side_en and c.side_dir:
            self.out_dir = self._write(self.out_dir, c.side_base, c.side_count, side_val)
        elif side_en:
            self.out_val = self._write(self.out_val, c.side_base, c.side_count, side_val)

        self.stalled = stall
        if stall:
            return
        self.delay = delay
        self.pc = jump if jump is not None else self._next_pc()
