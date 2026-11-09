"""programs/lcd1602.asm on the engine model, against a model HD44780 (model/hd44780.py), worst case on timing.

  1. power-on sequence (nibbles 3, 3, 3, 2 with the long wait): the display goes to 4-bit mode
  2. function set 0x28 (two lines), display on 0x0C, entry mode 0x06, clear 0x01 (long wait)
  3. text on line 1, DDRAM address 0xC0, text on line 2: the screen reads back as written
  4. home (0x02, long wait) and an overwrite of the first characters
  5. every edge inside the datasheet's slow-supply limits, no write while busy, none in the first 40 ms
Pins from base 8 (Tiny Tapeout uo[2..7]): D4-D7 = 8-11, RS = 12, E = 13. Run at two clocks (4 MHz, clkdiv 3;
40 MHz, clkdiv 39). `python model/test_lcd.py plant` runs four planted bugs instead, each of which must fail.
Run:  python model/test_lcd.py [plant]
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config
from hd44780 import HD44780

P = 8
SRC = open(os.path.join(ROOT, "programs", "lcd1602.asm")).read()
LINE1, LINE2 = "PROTOCOL EMU    ", "I2C 400k 0x50   "


class Display:
    def __init__(self, src, clk_hz, wait_power=True):
        self.prog = assemble(src)
        self.L = self.prog.labels
        cfg = Config.for_program(self.prog, clkdiv=round(clk_hz * 1e-6) - 1, out_base=P, out_count=4, set_base=P,
                                 set_count=5, side_base=P + 5, out_right=False)
        self.eng = Engine(self.prog, cfg)
        # the host's 40 ms power-on wait: really clocked at 4 MHz; at 40 MHz taken as already done (powered earlier)
        self.lcd = HD44780(clk_hz, powered_ns=0.0 if wait_power else -45e6)
        self.wait_power = wait_power
        self.clk_hz = clk_hz

    def step(self):
        e = self.eng
        v, d = e.out_val, e.out_dir
        bit = lambda p: (v >> p) & (d >> p) & 1
        self.lcd.clock(bit(P + 4), bit(P + 5), sum(bit(P + i) << i for i in range(4)))
        e.clock(0)

    def idle_us(self, us):
        for _ in range(round(us * self.clk_hz / 1e6)):
            self.step()

    def send(self, words, settle_us=6000):
        todo = list(words)
        guard = 0
        while todo:
            if self.eng.tx_put(todo[0]):
                todo.pop(0)
            self.step()
            guard += 1
            if guard > 100_000_000:
                raise RuntimeError("stuck")
        self.idle_us(settle_us)

    # host-side helpers, as pico/lcd1602.py does them
    def nib(self, n):
        return self.L["nib"] << 11 | n << 7

    def cmd(self, b, long=False):
        return self.L["cmd"] << 11 | b << 3 | int(long) << 2

    def data(self, b):
        return self.L["data"] << 11 | b << 3

    def init(self):
        if self.wait_power:
            self.idle_us(45_000)
        self.send([self.nib(3), self.nib(3), self.nib(3), self.nib(2)])
        self.send([self.cmd(0x28), self.cmd(0x0C), self.cmd(0x06), self.cmd(0x01, long=True)])

    def text(self, s):
        self.send([self.data(ord(c)) for c in s])


def check(name, ok, info=""):
    print("  %-62s %s %s" % (name, "ok" if ok else "FAIL", info))
    return 0 if ok else 1


def run_all(src, clk_hz, quiet=False):
    chk = (lambda n, ok, i="": 0 if ok else 1) if quiet else check
    if not quiet:
        print("\n-- %d MHz" % (clk_hz // 1_000_000))
    d = Display(src, clk_hz, wait_power=clk_hz <= 4_000_000)
    lcd = d.lcd
    bad = 0
    d.init()
    bad += chk("1. power-on sequence: 4-bit mode", not lcd.bits8 and lcd.fsets == 4, "%d function sets in 8-bit" % lcd.fsets)
    bad += chk("2. two lines, display on, increment, screen clear",
               lcd.lines2 and lcd.on and not lcd.cursor and lcd.inc and lcd.screen() == [" " * 16] * 2)
    d.text(LINE1.rstrip())
    d.send([d.cmd(0xC0)])
    d.text(LINE2.rstrip())
    bad += chk("3. line 1 and line 2 read back", lcd.screen() == [LINE1, LINE2], "|%s|%s|" % tuple(lcd.screen()))
    d.send([d.cmd(0x02, long=True)])
    d.text("Protocol")
    bad += chk("4. home, overwrite: 'Protocol EMU'", lcd.screen()[0] == "Protocol EMU    ", "|%s|" % lcd.screen()[0])
    m = lcd.min
    bad += chk("5. no timing breach, no write while busy", not lcd.errors, "; ".join(lcd.errors[:2]))
    if not quiet:
        print("     E high min %.0f ns, E cycle min %.0f ns, RS setup min %.0f ns, D setup min %.0f ns, hold min %.0f ns"
              % (m["e_high"], m["e_cycle"], m["rs_setup"], m["d_setup"], m["hold"]))
        print("     %d instructions and characters taken" % len(lcd.log))
    return bad


def plants():
    cases = [
        ("data changes as E falls (no hold)",
         "    mov    y, y            side 0  ; E low: the display takes the nibble; data held\n    out    pins, 4 ",
         "    out    pins, 4         side 0  ; E low and the next nibble at once\n    mov    y, y    "),
        ("short wait 32 us (under the 50 us busy time)",
         "short_loop:\n    jmp    y--, short_loop [1]", "short_loop:\n    jmp    y--, short_loop [0]"),
        ("long wait 2.6 ms (under the 4.1 ms power-on wait)",
         "long:\n    set    x, 31", "long:\n    set    x, 15"),
        ("characters sent with RS low", "    set    pins, 16                ; RS high",
         "    set    pins, 0                 ; RS high"),
    ]
    caught = 0
    for name, old, new in cases:
        assert SRC.count(old) == 1, old
        try:
            bad = run_all(SRC.replace(old, new), 4_000_000, quiet=True)
        except RuntimeError:
            bad = 1
        print("  planted: %-55s %s" % (name, "caught" if bad else "MISSED"))
        caught += bool(bad)
    print("\n==== %s (%d of %d planted bugs caught) ====" % ("PASS" if caught == len(cases) else "FAIL", caught, len(cases)))
    return caught == len(cases)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "plant":
        sys.exit(0 if plants() else 1)
    print("programs/lcd1602.asm: %d words" % len(assemble(SRC).words))
    bad = run_all(SRC, 4_000_000) + run_all(SRC, 40_000_000)
    print("\n==== %s (%d problems) ====" % ("FAIL" if bad else "PASS", bad))
    sys.exit(1 if bad else 0)
