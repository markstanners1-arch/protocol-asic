"""Clock-by-clock model of one engine, written from docs/isa.md (v0.1).

This is the reference ("the calculated values"): the Verilog engine must match it
on every system clock. Keep it plain and literal; speed doesn't matter, clarity does.

    eng = Engine(program, Config(...))
    popped = eng.clock(pins_in, push=word_or_None, pop=False)   # one system clock
    eng.out_val, eng.out_dir    # pin outputs after this clock
  Convenience: eng.tx_put(word) / eng.rx_get() queue a host push / pop for the next clock.
  Host FIFO timing follows docs/isa.md: decided from the state at the start of the clock.
"""
from collections import deque
from dataclasses import dataclass

M16 = 0xFFFF
M32 = 0xFFFFFFFF
FIFO_DEPTH = 4


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
    in_base: int = 0
    jmp_pin: int = 0
    out_right: bool = True
    in_right: bool = True
    fault_addr: int = 0

    @classmethod
    def for_program(cls, prog, **kw):
        """Take the wrap and side-set settings from an assembled program."""
        return cls(wrap_bottom=prog.wrap_bottom, wrap_top=prog.wrap_top,
                   side_count=prog.side_count, side_opt=prog.side_opt, **kw)


def _bitrev16(v):
    return int(f"{v & M16:016b}"[::-1], 2)


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
        self.rxf = deque()
        self.sync1 = self.sync2 = 0
        self.ticks = 0
        self.stalled = False
        self._push = None
        self._pop = False

    # ---- host side ----
    def tx_put(self, word):
        """Queue a host push for the next clock. False if it would be refused."""
        if len(self.txf) >= FIFO_DEPTH or self._push is not None:
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

    def _pins_from(self, base, count):
        return sum(self._pin(base + i) << i for i in range(count))

    @staticmethod
    def _write(reg, base, count, data):
        for i in range(count):
            p = (base + i) % 32
            reg = (reg & ~(1 << p)) | (((data >> i) & 1) << p)
        return reg & M32

    # ---- one system clock ----
    def clock(self, pins_in=0, push=None, pop=False):
        """One system clock. Returns the word the host popped, or None."""
        if self._push is not None:
            push, self._push = self._push, None
        if self._pop:
            pop, self._pop = True, False
        # host requests are judged on the state at the start of the clock
        push_ok = push is not None and len(self.txf) < FIFO_DEPTH
        pop_ok = pop and len(self.rxf) > 0
        popped = self.rxf[0] if pop_ok else None
        if self.div == 0:
            self.div = self.cfg.clkdiv
            self._tick()
        else:
            self.div -= 1
        if push_ok:
            self.txf.append(push & M16)
        if pop_ok:
            self.rxf.popleft()
        # synchroniser: the engine sees pins as they were 2 clocks ago
        self.sync2, self.sync1 = self.sync1, pins_in & M32
        return popped

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
            if self._pin(pin) != level:
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
                    6: lambda: self.sw}.get(src, lambda: 0)()
            data &= (1 << n) - 1
            if c.in_right:
                self.isr = ((self.isr >> n) | (data << (16 - n))) & M16 if n < 16 else data
            else:
                self.isr = ((self.isr << n) | data) & M16
            self.isr_count = min(16, self.isr_count + n)

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
                if cond and self.osr_count < 16:
                    pass
                elif not self.txf:
                    if block:
                        stall = True
                    else:
                        self.osr, self.osr_count = self.x, 0
                else:
                    self.osr, self.osr_count = self.txf.popleft(), 0

        elif op == 5:                                  # MOV
            dst, mop, src = a >> 5, (a >> 3) & 3, a & 7
            v = {0: lambda: self._pins_from(c.in_base, 16), 1: lambda: self.x, 2: lambda: self.y,
                 3: lambda: 0, 4: lambda: self.sw,
                 5: lambda: (len(self.txf) & 15) | ((len(self.rxf) & 15) << 4),
                 6: lambda: self.isr, 7: lambda: self.osr}[src]()
            if mop == 1:   v = ~v & M16
            elif mop == 2: v = _bitrev16(v)
            if dst == 0:   self.out_val = self._write(self.out_val, c.out_base, c.out_count, v)
            elif dst == 1: self.x = v
            elif dst == 2: self.y = v
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

        # side-set happens on every executed step, stalled or not, and wins over the instruction
        if side_en:
            self.out_val = self._write(self.out_val, c.side_base, c.side_count, side_val)

        self.stalled = stall
        if stall:
            return
        self.delay = delay
        self.pc = jump if jump is not None else self._next_pc()
