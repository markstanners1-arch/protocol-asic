"""programs/onewire.asm on the engine model, against a model DS18B20 (model/ds18b20.py), worst case on timing.

  1. no device on the line: the reset reports no presence pulse
  2. presence; READ ROM: family 0x28, the model's serial, CRC-8 good
  3. SKIP ROM, CONVERT T: read slots give 0 while converting, then 1; SKIP ROM, READ SCRATCHPAD: 9 bytes, CRC good,
     the temperature equal to the model's (positive and negative)
  4. MATCH ROM with the right ROM code: the device answers; with a wrong one it stays silent (reads 0xFF)
  5. WRITE SCRATCHPAD (TH, TL, config), read back
  6. every low pulse the engine drives is inside the standard: reset 480-960 us, write-1 1-15 us, write-0 60-120 us;
     slots at least 61 us apart; no ambiguous bit at the device
Run at two clocks (4 MHz, clkdiv 7; 40 MHz, clkdiv 79). `python model/test_onewire.py plant` runs three planted
timing bugs instead, each of which must fail.
Run:  python model/test_onewire.py [plant]
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config
from ds18b20 import DS18B20, crc8

PIN = 0
SRC = open(os.path.join(ROOT, "programs", "onewire.asm")).read()


class Line:
    def __init__(self, src, clk_hz, dev):
        self.prog = assemble(src)
        L = self.prog.labels
        self.RESET, self.XFER = L["reset"], L["xfer"]
        clkdiv = round(clk_hz * 2e-6) - 1
        cfg = Config.for_program(self.prog, clkdiv=clkdiv, set_base=PIN, set_count=1, out_base=PIN, out_count=1,
                                 in_base=PIN, out_right=True, in_right=True)
        self.eng = Engine(self.prog, cfg)
        self.dev = dev
        self.us = 1e6 / clk_hz
        self.t = 0
        self.dev_low = False
        self.m_last, self.m_fall = 0, None
        self.pulses = []           # (start us, length us) of every low the engine drives
        self.replies = []

    def master_low(self):
        e = self.eng
        return bool((e.out_dir >> PIN) & 1 and not (e.out_val >> PIN) & 1)

    def run(self, words, replies):
        """Feed the words; run until that many replies have come back."""
        todo = list(words)
        got = []
        guard = 0
        while len(got) < replies:
            if todo and self.eng.tx_put(todo[0]):
                todo.pop(0)
            m = self.master_low()
            line = 0 if (m or self.dev_low) else 1
            if self.dev is not None:
                self.dev_low = self.dev.clock(line)
                line = 0 if (m or self.dev_low) else 1
            if m and not self.m_last:
                self.m_fall = self.t
            elif self.m_last and not m:
                self.pulses.append((self.m_fall * self.us, (self.t - self.m_fall) * self.us))
            self.m_last = m
            self.eng.clock(line << PIN)
            r = self.eng.rx_get()
            if r is not None:
                got.append(r)
            self.t += 1
            guard += 1
            if guard > 50_000_000:
                raise RuntimeError("no reply")
        return got

    # host-side helpers, as pico/ds18b20.py does them
    def reset(self):
        return (self.run([self.RESET], 1)[0] >> 15) == 0          # True = presence

    def xfer(self, data):
        return [w >> 8 for w in self.run([b << 5 | self.XFER for b in data], len(data))]

    def write(self, *data):
        self.xfer(list(data))

    def read(self, n):
        return self.xfer([0xFF] * n)


def temp_of(sp):
    raw = sp[0] | sp[1] << 8
    if raw & 0x8000:
        raw -= 0x10000
    return raw / 16.0


def check(name, ok, info=""):
    print("  %-62s %s %s" % (name, "ok" if ok else "FAIL", info))
    return 0 if ok else 1


def run_all(src, clk_hz, quick=False, quiet=False):
    bad = 0
    if not quiet:
        print("\n-- %d MHz" % (clk_hz // 1_000_000))
    out = print if not quiet else (lambda *a: None)

    def chk(name, ok, info=""):
        if not quiet:
            return check(name, ok, info)
        return 0 if ok else 1

    nobody = Line(src, clk_hz, None)
    bad += chk("1. no device: no presence pulse", nobody.reset() is False)

    dev = DS18B20(clk_hz, temp_c=23.5625, conv_us=3000)
    w = Line(src, clk_hz, dev)
    bad += chk("2. presence pulse", w.reset() is True)
    w.write(0x33)
    rom = w.read(8)
    bad += chk("   READ ROM = the model's ROM, CRC-8 good", rom == dev.rom and crc8(rom[:7]) == rom[7],
               " ".join("%02x" % b for b in rom))
    if not quick:
        w.reset(); w.write(0xCC, 0x44)
        polls = []
        while True:
            b = w.read(1)[0]
            polls.append(b)
            if b == 0xFF or len(polls) > 200:
                break
        bad += chk("3. CONVERT T: busy reads 0, then done", polls[0] == 0x00 and polls[-1] == 0xFF and
                   set(polls[:-1]) <= {0x00, 0xFE, 0x80} , "%d polls" % len(polls))
        w.reset(); w.write(0xCC, 0xBE)
        sp = w.read(9)
        bad += chk("   READ SCRATCHPAD: CRC good, 23.5625 C", crc8(sp[:8]) == sp[8] and temp_of(sp) == 23.5625,
                   " ".join("%02x" % b for b in sp))
        dev.temp_c = -10.125
        w.reset(); w.write(0xCC, 0x44)
        while w.read(1)[0] != 0xFF:
            pass
        w.reset(); w.write(0xCC, 0xBE)
        sp = w.read(9)
        bad += chk("   negative temperature: -10.125 C", crc8(sp[:8]) == sp[8] and temp_of(sp) == -10.125,
                   "%.4f" % temp_of(sp))
        w.reset(); w.write(0x55, *dev.rom, 0xBE)
        sp = w.read(9)
        bad += chk("4. MATCH ROM (right code): scratchpad, CRC good", crc8(sp[:8]) == sp[8] and temp_of(sp) == -10.125)
        wrong = list(dev.rom); wrong[3] ^= 0x01
        w.reset(); w.write(0x55, *wrong, 0xBE)
        bad += chk("   MATCH ROM (wrong code): silent", w.read(9) == [0xFF] * 9)
        w.reset(); w.write(0xCC, 0x4E, 0x12, 0x34, 0x1F)
        w.reset(); w.write(0xCC, 0xBE)
        sp = w.read(9)
        bad += chk("5. WRITE SCRATCHPAD then read: TH 12 TL 34 config 1F", sp[2:5] == [0x12, 0x34, 0x1F] and
                   crc8(sp[:8]) == sp[8])
    resets = [p for p in w.pulses if p[1] >= 200]
    ones = [p for p in w.pulses if p[1] < 30]
    zeros = [p for p in w.pulses if 30 <= p[1] < 200]
    starts = [p[0] for p in w.pulses if p[1] < 200]
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b - a < 200]
    bad += chk("6. reset lows 480-960 us", resets and all(480 <= p[1] <= 960 for p in resets),
               "%.1f-%.1f us" % (min(p[1] for p in resets), max(p[1] for p in resets)))
    bad += chk("   write-1 lows 1-15 us", ones and all(1 <= p[1] <= 15 for p in ones),
               "%.2f-%.2f us" % (min(p[1] for p in ones), max(p[1] for p in ones)))
    bad += chk("   write-0 lows 60-120 us", zeros and all(60 <= p[1] <= 120 for p in zeros),
               "%.2f-%.2f us" % (min(p[1] for p in zeros), max(p[1] for p in zeros)))
    bad += chk("   slots at least 61 us apart", gaps and min(gaps) >= 61, "min %.1f us" % min(gaps))
    bad += chk("   the device saw no ambiguous bit", not dev.errors, "; ".join(dev.errors[:2]))
    if not quiet:
        print("  (%d resets, %d write-1 / read slots, %d write-0 slots)" % (len(resets), len(ones), len(zeros)))
    return bad


def plants():
    cases = [
        ("sample at 16 us (too late for a device's 15 us zero)",
         "out    pindirs, 1      [3]", "out    pindirs, 1      [5]"),
        ("reset low 450 us (one loop short)",
         "    set    x, 7\n    set    pindirs, 1", "    set    x, 6\n    set    pindirs, 1"),
        ("write-0 released at 52 us (under 60)",
         "in     pins, 1         [25]", "in     pins, 1         [19]"),
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
    print("programs/onewire.asm: %d words" % len(assemble(SRC).words))
    bad = run_all(SRC, 4_000_000) + run_all(SRC, 40_000_000, quick=True)
    print("\n==== %s (%d problems) ====" % ("FAIL" if bad else "PASS", bad))
    sys.exit(1 if bad else 0)
