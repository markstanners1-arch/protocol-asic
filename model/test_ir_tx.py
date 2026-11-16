"""programs/ir_tx.asm on the engine model: the NEC transmitter, checked on its pin and end to end through programs/ir_nec.asm.

Two engines run together, clock by clock. Engine A runs ir_tx.asm and drives the LED pin (engine pin 9). A model receiver module
turns the LED's carrier into the demodulated signal (low while carrier has been seen in the last 40 us, high otherwise, like a
VS1838) and feeds it to pin 1 of engine B, which runs ir_nec.asm. Checks:
  1. the LED pin is driven and low while the host has sent nothing (20 ms): no carrier
  2. the carrier: 38 kHz within 2 % in the bit bursts (38.4 kHz), within 3 % averaged over the leader (37.7 kHz)
  3. frame timing from the LED edges, an independent decoder in this file: leader burst 9 ms and space 4.5 ms, bit burst and space
     within 8 %, each bit's burst + space within 2 % of 1125 us (0) or 2250 us (1); the space after bit 16 may be longer (the word fetch)
  4. that decoder reads back the 32 bits that were sent, for plain NEC (address 00, command 45), a frame of all zeros, a frame of
     all ones (the longest, 86 ms), and the Manhattan remote's button 1 (words 2916, 5CB7: no inverse rule)
  5. after the closing burst the line stays low (no carrier for 30 ms)
  6. end to end: engine B (ir_nec.asm) pushes exactly the two words that were sent
Run:  python model/test_ir_tx.py [clk_hz_in_MHz]   (default 12 = the kit; 50 = the ASIC. Tick 8.67 us: clkdiv 103 / 433)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

LED_PIN, IR_PIN = 9, 1
tx_prog = assemble(open(os.path.join(ROOT, "programs", "ir_tx.asm")).read())
rx_prog = assemble(open(os.path.join(ROOT, "programs", "ir_nec.asm")).read())


class Link:
    def __init__(self, clk_hz):
        self.clk_hz = clk_hz
        tx_div = round(clk_hz / (3 * 38400)) - 1
        rx_div = round(clk_hz * 50e-6) - 1
        self.tx = Engine(tx_prog, Config.for_program(tx_prog, clkdiv=tx_div, set_base=LED_PIN, set_count=1, out_right=True))
        self.rx = Engine(rx_prog, Config.for_program(rx_prog, clkdiv=rx_div, in_base=IR_PIN, jmp_pin=IR_PIN, in_right=True, out_right=True))
        self.t = 0
        self.queue = []
        self.pushes = []            # (clock, word) from engine B
        self.edges = []             # (clock, level) of the LED pin
        self.led = 0
        self.last_high = -10**9
        self.hold = int(clk_hz * 40e-6)

    def clock(self):
        e = self.tx
        if self.queue and e.tx_put(self.queue[0]):
            self.queue.pop(0)
        got = self.rx.rx_get()
        if got is not None:
            self.pushes.append((self.t, got))
        led = ((e.out_val >> LED_PIN) & 1) if (e.out_dir >> LED_PIN) & 1 else 0
        if led != self.led:
            self.edges.append((self.t, led)); self.led = led
        if led:
            self.last_high = self.t
        demod = 0 if self.t - self.last_high < self.hold else 1     # low while carrier is present
        e.clock(0)
        self.rx.clock(demod << IR_PIN)
        self.t += 1

    def run_ms(self, ms):
        for _ in range(int(self.clk_hz * ms / 1000)):
            self.clock()

    def us(self, clocks):
        return clocks / self.clk_hz * 1e6


def bursts(edges, clk_hz):
    """Group the LED's rising edges into bursts (a gap over 60 us ends one). Returns [(start us, end us, rising-edge count)]:
    start = first rising edge, end = last falling edge."""
    out = []; cur = None; last_rise = None
    for t, lvl in edges:
        us = t / clk_hz * 1e6
        if lvl == 1:
            if cur is None or us - last_rise > 60:
                if cur: out.append(cur)
                cur = [us, us, 0]
            cur[2] += 1; last_rise = us
        elif cur:
            cur[1] = us
    if cur: out.append(cur)
    return out


def decode_nec(bs):
    """An independent decoder of the burst list: leader 9 ms + 4.5 ms space, then 32 (burst, space) pairs. Returns the 32-bit word
    (first bit sent = bit 0) or None."""
    if len(bs) < 34: return None
    if not (8000 < bs[0][1] - bs[0][0] < 10000 and 4000 < bs[1][0] - bs[0][1] < 5000): return None
    w = 0
    for i in range(32):
        space = bs[2 + i][0] - bs[1 + i][1]
        w |= (1 if space > 1100 else 0) << i
    return w


def main(mhz):
    clk_hz = mhz * 1e6
    ok = True

    def check(what, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"  {what:66s} {'ok' if good else 'WRONG'} {detail}")

    link = Link(clk_hz)
    print(f"clock {mhz} MHz: transmitter clkdiv {link.tx.cfg.clkdiv}, tick {(link.tx.cfg.clkdiv + 1) / clk_hz * 1e6:.2f} us; decoder clkdiv {link.rx.cfg.clkdiv}")
    link.run_ms(20)
    check("LED pin driven and low for 20 ms with nothing sent",
          (link.tx.out_dir >> LED_PIN) & 1 == 1 and link.edges == [] and link.pushes == [])

    frames = [("plain NEC, address 00 command 45", 0xBA45FF00),
              ("all zeros (shortest spaces)", 0x00000000),
              ("all ones (longest frame)", 0xFFFFFFFF),
              ("Manhattan button 1, words 2916 5CB7", 0x5CB72916)]
    if mhz > 20:
        frames = [frames[0], frames[3]]          # the 50 MHz model is slow: two frames
    for name, word in frames:
        e0, p0 = len(link.edges), len(link.pushes)
        link.queue += [word & 0xFFFF, word >> 16]
        link.run_ms(112)
        edges = link.edges[e0:]
        bs = bursts(edges, clk_hz)
        print(f"-- {name}: {len(bs)} bursts")
        if len(bs) < 34:
            check("34 bursts (leader, 32 bits, closing)", False, f"got {len(bs)}"); continue
        # carrier
        def freq(b):
            r = [t for t, l in edges if l == 1 and b[0] <= t / clk_hz * 1e6 <= b[1]]
            return (len(r) - 1) / ((r[-1] - r[0]) / clk_hz)
        fl = freq(bs[0]); fb = [freq(b) for b in bs[1:]]
        check("carrier in the leader, averaged: 38 kHz within 3 %", abs(fl - 38000) / 38000 < 0.03, f"{fl/1000:.2f} kHz")
        check("carrier in every bit burst: 38 kHz within 2 %", all(abs(f - 38000) / 38000 < 0.02 for f in fb), f"{min(fb)/1000:.2f} to {max(fb)/1000:.2f} kHz")
        lead_b = bs[0][1] - bs[0][0]; lead_s = bs[1][0] - bs[0][1]
        check("leader burst 9 ms within 5 %", abs(lead_b - 9000) / 9000 < 0.05, f"{lead_b/1000:.2f} ms")
        check("leader space 4.5 ms within 5 %", abs(lead_s - 4500) / 4500 < 0.05, f"{lead_s/1000:.2f} ms")
        bad = 0; worst = 0
        for i in range(32):
            b = bs[1 + i][1] - bs[1 + i][0]; s = bs[2 + i][0] - bs[1 + i][1]; one = (word >> i) & 1
            ns = 1687.5 if one else 562.5
            per = (bs[2 + i][0] - bs[1 + i][0]); nper = 2250 if one else 1125
            seam = i == 15          # the second word is fetched after bit 16: that space is 5 ticks longer
            if abs(b - 562.5) / 562.5 > 0.08 or abs(s - ns) / ns > (0.13 if seam else 0.08) or abs(per - nper) / nper > (0.06 if seam else 0.02):
                bad += 1
            if not seam: worst = max(worst, abs(per - nper) / nper)
        check("all 32 bursts and spaces within 8 %, periods within 2 % (seam bit 16: 13 % and 6 %)", bad == 0, f"{bad} bad, worst period error {worst*100:.1f} %")
        check("independent decoder reads back the word sent", decode_nec(bs) == word, f"{decode_nec(bs):08X}" if decode_nec(bs) is not None else "none")
        last = bs[-1]
        check("closing burst is a bit-burst long", abs((last[1] - last[0]) - 562.5) / 562.5 < 0.08, f"{(last[1]-last[0]):.0f} us")
        check("no carrier after the closing burst (line low)", link.led == 0 and link.t / clk_hz * 1e6 - bs[-1][1] > 20000)
        got = [w for _, w in link.pushes[p0:]]
        check("engine B (ir_nec.asm) pushes the two words sent", got == [word & 0xFFFF, word >> 16], f"{[f'{g:04X}' for g in got]}")
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(float(sys.argv[1]) if len(sys.argv) > 1 else 12) else 1)
