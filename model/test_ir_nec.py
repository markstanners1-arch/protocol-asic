"""programs/ir_nec.asm on the engine model, decoding a model IR receiver's output.

The receiver model: a list of (level, microseconds) segments is played into engine pin 1 clock by clock. Frames are
built from (address, command) pairs exactly as a NEC remote sends them (9 ms burst, 4.5 ms space, 32 bits LSB first
with their inverses, closing burst), repeat frames as 9 ms / 2.25 ms / 562.5 us, and the whole frame can be scaled
(a remote 5 % fast or slow). The program pushes two words a frame (address | ~address << 8, then command | ~command
<< 8) and 0xFFFF for a repeat; host_decode() here pairs them the way the sketch does. Checks:
  1. nothing pushed while the line idles, nor for stray short pulses
  2. one frame: the two words, decoded to the right address and command
  3. a run of frames at the remote's 108 ms period, and a frame followed by held-button repeats
  4. frames 5 % fast and 5 % slow decode the same
  5. a frame whose ~command is wrong is pushed as sent, and the host check flags it
  6. extended NEC (16-bit address) comes through as the raw address
  7. a frame cut short after 20 bits leaves one unpaired word, and the next frame decodes correctly
Run:  python model/test_ir_nec.py [clkdiv]   (default 599, the 12 MHz kit's 50 us tick; 2499 = the ASIC at 50 MHz)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

IR_PIN = 1
REPEAT = 0xFFFF
prog = assemble(open(os.path.join(ROOT, "programs", "ir_nec.asm")).read())


def pair(lo):
    return lo | ((~lo & 0xFF) << 8)


class Receiver:
    def __init__(self, clkdiv, clk_hz):
        self.eng = Engine(prog, Config.for_program(prog, clkdiv=clkdiv, in_base=IR_PIN, jmp_pin=IR_PIN,
                                                   in_right=True, out_right=True))
        self.clk_hz = clk_hz
        self.pushes = []            # (time in clocks, word)
        self.t = 0
        self.level = 1              # the receiver idles high

    def play(self, level, us):
        self.level = level
        for _ in range(int(self.clk_hz * us / 1e6 + 0.5)):
            got = self.eng.rx_get()
            if got is not None:
                self.pushes.append((self.t, got))
            self.eng.clock(level << IR_PIN)
            self.t += 1

    def idle(self, ms):
        self.play(1, ms * 1000)

    def bits(self, value, n, scale):
        for i in range(n):
            self.play(0, 562.5 * scale)
            self.play(1, (1687.5 if (value >> i) & 1 else 562.5) * scale)

    def frame(self, addr, cmd, scale=1.0, extended=False, bad_inverse=0, cut_after=None):
        """One NEC frame then the gap that makes the 108 ms period. extended: addr is 16 bits, no inverse.
        bad_inverse: XORed into the inverted command byte. cut_after: stop sending after this many bits."""
        word = (addr | ((~addr & 0xFF) << 8)) if not extended else (addr & 0xFFFF)
        word |= (cmd | (((~cmd & 0xFF) ^ bad_inverse) << 8)) << 16
        self.play(0, 9000 * scale)
        self.play(1, 4500 * scale)
        self.bits(word, 32 if cut_after is None else cut_after, scale)
        if cut_after is None:
            self.play(0, 562.5 * scale)
        self.idle(108 - 67.5)

    def repeat(self, scale=1.0):
        self.play(0, 9000 * scale)
        self.play(1, 2250 * scale)
        self.play(0, 562.5 * scale)
        self.idle(108 - 11.8)

    def words(self):
        return [w for _, w in self.pushes]


def host_decode(pushes, clk_hz):
    """The sketch's view: 0xFFFF is a repeat; otherwise a word is an address pair and the command pair must follow
    within 60 ms, else the frame was incomplete. Returns one string per frame."""
    out, i = [], 0
    while i < len(pushes):
        t, w = pushes[i]
        if w == REPEAT:
            out.append("repeat"); i += 1; continue
        if i + 1 < len(pushes) and pushes[i + 1][1] != REPEAT and pushes[i + 1][0] - t < 0.060 * clk_hz:
            t2, w2 = pushes[i + 1]
            a_ok = (w >> 8) == (~w & 0xFF)
            c_ok = (w2 >> 8) == (~w2 & 0xFF)
            s = f"addr {w & 0xFF:02X} cmd {w2 & 0xFF:02X}" if a_ok else f"addr {w:04X} cmd {w2 & 0xFF:02X}"
            out.append(s + ("" if c_ok else " BAD INVERSE"))
            i += 2
        else:
            out.append(f"incomplete {w:04X}"); i += 1
    return out


def main(clkdiv):
    clk_hz = 12e6 if clkdiv == 599 else 50e6 if clkdiv == 2499 else 12e6
    tick_us = (clkdiv + 1) / clk_hz * 1e6
    ok = True

    def check(what, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  {what:62s} {'ok' if good else 'WRONG: got ' + repr(got) + ', wanted ' + repr(want)}")

    rx = Receiver(clkdiv, clk_hz)
    print(f"clkdiv {clkdiv}: tick {tick_us:.1f} us")
    rx.idle(100)
    check("nothing pushed while the line idles (100 ms)", rx.words(), [])
    rx.play(0, 600); rx.play(1, 1200); rx.play(0, 300); rx.idle(20)      # a stray bit, a glitch
    rx.play(0, 3000); rx.idle(20)                                        # a burst too short for a leader
    check("stray pulses (0.6 ms, 0.3 ms, 3 ms bursts): nothing pushed", rx.words(), [])

    rx.frame(0x00, 0x45)
    check("one frame addr 00 cmd 45: two words FF00, BA45", rx.words(), [pair(0x00), pair(0x45)])
    check("  decoded by the host", host_decode(rx.pushes, clk_hz), ["addr 00 cmd 45"])
    check("  both words within 36 ms", rx.pushes[1][0] - rx.pushes[0][0] < 0.036 * clk_hz, True)

    rx.pushes.clear()
    seq = [(0x00, 0x46), (0x00, 0x47), (0x10, 0xA5), (0xFF, 0x00)]
    for a, c in seq:
        rx.frame(a, c)
    check("four frames at the 108 ms period", host_decode(rx.pushes, clk_hz), [f"addr {a:02X} cmd {c:02X}" for a, c in seq])

    rx.pushes.clear()
    rx.frame(0x00, 0x15); rx.repeat(); rx.repeat(); rx.repeat()
    check("a frame then three repeats (button held)", host_decode(rx.pushes, clk_hz), ["addr 00 cmd 15"] + ["repeat"] * 3)

    rx.pushes.clear()
    rx.frame(0x00, 0x5A, scale=0.95); rx.repeat(scale=0.95)
    rx.frame(0x00, 0xA5, scale=1.05); rx.repeat(scale=1.05)
    check("frames 5 % fast and 5 % slow, with repeats", host_decode(rx.pushes, clk_hz),
          ["addr 00 cmd 5A", "repeat", "addr 00 cmd A5", "repeat"])

    rx.pushes.clear()
    rx.frame(0x00, 0x45, bad_inverse=0x10)
    check("wrong ~command: pushed as sent, host flags it", host_decode(rx.pushes, clk_hz), ["addr 00 cmd 45 BAD INVERSE"])
    check("  the word carries the bad byte", rx.words()[1], 0x45 | ((0xBA ^ 0x10) << 8))

    rx.pushes.clear()
    rx.frame(0x6B86, 0x12, extended=True)
    check("extended NEC (16-bit address 6B86)", host_decode(rx.pushes, clk_hz), ["addr 6B86 cmd 12"])

    rx.pushes.clear()
    rx.frame(0x00, 0x45, cut_after=20)
    rx.frame(0x00, 0x46)
    check("frame cut short after 20 bits, then a good one", host_decode(rx.pushes, clk_hz),
          ["incomplete FF00", "addr 00 cmd 46"])
    rx.pushes.clear()
    rx.frame(0x00, 0x45, cut_after=9)
    rx.frame(0x00, 0x47)
    check("frame cut short after 9 bits: nothing, then a good one", host_decode(rx.pushes, clk_hz), ["addr 00 cmd 47"])
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(int(sys.argv[1]) if len(sys.argv) > 1 else 599) else 1)
