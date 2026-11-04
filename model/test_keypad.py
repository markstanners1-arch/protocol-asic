"""programs/keypad.asm on the engine model, scanning a model 4x4 matrix keypad.

The keypad model: a key (row r, column c) joins row pin 16+r to column pin 4+c. A row reads low when any of its
pressed keys is on a column the engine is pulling low; otherwise the pull-up holds it high. Checks:
  1. nothing pushed while nothing is pressed
  2. one key: exactly one push, the right bit (4*(3-c)+r); release: one push of 0
  3. a key that bounces for 5 ms on press and on release: still exactly one push each way
  4. two keys at once, then one let go
  5. only ever one column driven at a time, and never driven high
  6. a 20 ms pause after a change, and a scan of 14 ticks (280 us)
Run:  python model/test_keypad.py [clkdiv]   (default 239, the 12 MHz kit's 20 us tick)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

COL0, ROW0 = 4, 16
prog = assemble(open(os.path.join(ROOT, "programs", "keypad.asm")).read())


def bit(r, c):
    return 4 * (3 - c) + r


class Keypad:
    def __init__(self, clkdiv, clk_hz):
        self.eng = Engine(prog, Config.for_program(prog, clkdiv=clkdiv, set_base=COL0, set_count=4,
                                                   in_base=ROW0, in_right=False, out_right=False))
        self.clk_hz = clk_hz
        self.pressed = set()
        self.pushes = []            # (time in clocks, map)
        self.t = 0
        self.bad_drive = 0          # a column driven high, or two columns driven at once
        self.col_lows = []          # (start clock, column) of each column pull-down, for the scan timing

    def rows(self):
        e = self.eng
        drv = [(e.out_dir >> (COL0 + c)) & 1 for c in range(4)]
        if sum(drv) > 1 or any(drv[c] and (e.out_val >> (COL0 + c)) & 1 for c in range(4)):
            self.bad_drive += 1
        low = {c for c in range(4) if drv[c]}
        if low and (not self.col_lows or self.col_lows[-1][1] != min(low)):
            self.col_lows.append((self.t, min(low)))
        v = 0
        for r in range(4):
            if not any((r, c) in self.pressed for c in low):
                v |= 1 << r
        return v

    def run(self, clocks):
        for _ in range(clocks):
            got = self.eng.rx_get()
            if got is not None:
                self.pushes.append((self.t, got))
            self.eng.clock(self.rows() << ROW0)
            self.t += 1

    def ms(self, n):
        return int(self.clk_hz * n / 1000)

    def bounce(self, key, ms, period_us=300):
        """The contact makes and breaks every period_us for ms, ending in the state it started."""
        start = key in self.pressed
        for i in range(int(ms * 1000 / period_us)):
            if key in self.pressed:
                self.pressed.discard(key)
            else:
                self.pressed.add(key)
            self.run(int(self.clk_hz * period_us / 1e6))
        if (key in self.pressed) != start:
            self.pressed.symmetric_difference_update({key})


def main(clkdiv):
    clk_hz = 12e6 if clkdiv == 239 else 50e6 if clkdiv == 999 else 12e6
    tick_us = (clkdiv + 1) / clk_hz * 1e6
    ok = True

    def check(what, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  {what:60s} {'ok' if good else 'WRONG: got ' + repr(got) + ', wanted ' + repr(want)}")

    kp = Keypad(clkdiv, clk_hz)
    print(f"clkdiv {clkdiv}: tick {tick_us:.1f} us")
    kp.run(kp.ms(50))
    check("nothing pushed while nothing is pressed (50 ms)", kp.pushes, [])
    scans = [t for t, c in kp.col_lows if c == 0]
    period = (scans[-1] - scans[0]) / (len(scans) - 1) / clk_hz * 1e6
    check("scan period 14 ticks", round(period / tick_us), 14)

    # one clean key: '5' is row 1, column 1
    kp.pressed.add((1, 1)); t0 = kp.t
    kp.run(kp.ms(50))
    check("key 5 pressed: one push", [m for _, m in kp.pushes], [1 << bit(1, 1)])
    check("seen within one scan (under 0.5 ms)", kp.pushes[0][0] - t0 < kp.ms(0.5), True)
    first_scan_after = min((t for t, c in kp.col_lows if c == 0 and t > kp.pushes[0][0]), default=None)
    pause_ms = (first_scan_after - kp.pushes[0][0]) / clk_hz * 1e3
    check("20 ms pause before scanning again (20-21 ms)", 20 <= pause_ms <= 21, True)
    kp.pressed.discard((1, 1)); kp.run(kp.ms(50))
    check("key 5 released: one push of 0", [m for _, m in kp.pushes], [1 << bit(1, 1), 0])

    # a bouncing key: 'D' is row 3, column 3
    kp.pushes.clear()
    kp.pressed.add((3, 3)); kp.bounce((3, 3), 5); kp.run(kp.ms(50))
    check("key D with 5 ms of bounce: one push", [m for _, m in kp.pushes], [1 << bit(3, 3)])
    kp.pressed.discard((3, 3)); kp.bounce((3, 3), 5); kp.run(kp.ms(50))
    check("released with 5 ms of bounce: one push of 0", [m for _, m in kp.pushes], [1 << bit(3, 3), 0])

    # two keys on one row: '1' (0,0) and 'A' (0,3): with push-pull columns this would short two drivers
    kp.pushes.clear()
    kp.pressed.add((0, 0)); kp.run(kp.ms(30)); kp.pressed.add((0, 3)); kp.run(kp.ms(30))
    check("1 then A: two pushes, both bits in the second", [m for _, m in kp.pushes],
          [1 << bit(0, 0), 1 << bit(0, 0) | 1 << bit(0, 3)])
    kp.pressed.discard((0, 0)); kp.run(kp.ms(30))
    check("1 let go: A alone", kp.pushes[-1][1], 1 << bit(0, 3))
    kp.pressed.discard((0, 3)); kp.run(kp.ms(30))

    # every key, one at a time
    kp.pushes.clear()
    for r in range(4):
        for c in range(4):
            kp.pressed.add((r, c)); kp.run(kp.ms(25)); kp.pressed.discard((r, c)); kp.run(kp.ms(25))
    want = []
    for r in range(4):
        for c in range(4):
            want += [1 << bit(r, c), 0]
    check("all 16 keys in turn: 32 pushes, each the right bit", [m for _, m in kp.pushes], want)
    check("only one column ever driven, never high", kp.bad_drive, 0)
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 239) else 1)
