"""programs/uart_rx.asm on the engine model: a UART line driven by a model sender, then a loopback from uart_tx.

Checks, at the kit's and the ASIC's dividers:
  1. bytes with idle gaps, and twenty bytes back to back with no gap at all: every one pushed as 0x100 | byte
  2. a sender 2 % fast and 2 % slow back to back (a UART's usual budget each end), 4 % either way with gaps
  3. a glitch on the line (a low pulse of 2 ticks, a quarter of a bit): nothing pushed
  4. a framing error (stop bit low): the byte pushed with bit 8 clear; a break (line low for 20 bit times): one 0x0000,
     then nothing until the line is idle again and the next real byte comes through
  5. loopback: a second engine runs uart_tx at the same divider, its pin feeding this one; 32 bytes through
Run:  python model/test_uart_rx.py [clkdiv ...]   (default 12 155 53: 115200 and 9600 at 12 MHz, 115200 at 50 MHz)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

rx_prog = assemble(open(os.path.join(ROOT, "programs", "uart_rx.asm")).read())
tx_prog = assemble(open(os.path.join(ROOT, "programs", "uart_tx.asm")).read())


class Line:
    """The engine model with a UART line on pin 0 that the test drives clock by clock."""
    def __init__(self, clkdiv):
        self.eng = Engine(rx_prog, Config.for_program(rx_prog, clkdiv=clkdiv, in_base=0, jmp_pin=0, in_right=True))
        self.tick = clkdiv + 1
        self.got = []

    def drive(self, levels):
        for lv in levels:
            w = self.eng.rx_get()
            if w is not None:
                self.got.append(w)
            self.eng.clock(lv & 1)

    def idle(self, bits=3):
        self.drive([1] * (bits * 8 * self.tick))

    def byte(self, b, bitlen=None, stop=1):
        bitlen = bitlen or 8 * self.tick
        bits = [0] + [(b >> k) & 1 for k in range(8)] + [stop]
        self.drive([v for v in bits for _ in range(bitlen)])

    def take(self):
        g, self.got = self.got, []
        return g


def check(name, got, want, ok):
    good = got == want
    print(f"  {name:58s} {'ok' if good else 'WRONG: got ' + ' '.join('%04X' % w for w in got) + ' wanted ' + ' '.join('%04X' % w for w in want)}")
    return ok and good


def run(clkdiv):
    tick = clkdiv + 1
    print(f"clkdiv {clkdiv}: tick {tick} clocks, bit {8 * tick} clocks")
    ok = True
    ln = Line(clkdiv)
    ln.idle(4)

    data = [0x55, 0xAA, 0x00, 0xFF, 0x41, 0x80, 0x01, 0x7E]
    for b in data:
        ln.byte(b); ln.idle(2)
    ok = check("bytes with idle gaps", ln.take(), [0x100 | b for b in data], ok)

    seq = [(i * 37 + 11) & 0xFF for i in range(20)]
    for b in seq:
        ln.byte(b)                                    # no gap at all between the stop bit and the next start
    ln.idle(2)
    ok = check("twenty bytes back to back", ln.take(), [0x100 | b for b in seq], ok)

    for pct in (-2, 2):                                # back to back, no gap: the usual UART budget each end
        bitlen = round(8 * tick * (1 + pct / 100))
        for b in seq[:10]:
            ln.byte(b, bitlen)
        ln.idle(2)
        ok = check(f"sender {pct:+d} % off, back to back ({bitlen} clocks a bit)", ln.take(), [0x100 | b for b in seq[:10]], ok)
    for pct in (-4, 4):                                # with a gap between bytes
        bitlen = round(8 * tick * (1 + pct / 100))
        for b in seq[:10]:
            ln.byte(b, bitlen); ln.idle(1)
        ln.idle(2)
        ok = check(f"sender {pct:+d} % off, with gaps ({bitlen} clocks a bit)", ln.take(), [0x100 | b for b in seq[:10]], ok)

    ln.drive([0] * (2 * tick)); ln.idle(2)             # a 2-tick glitch: a quarter of a bit
    ok = check("a 2-tick glitch", ln.take(), [], ok)
    ln.byte(0x5A); ln.idle(2)
    ok = check("a byte after the glitch", ln.take(), [0x15A], ok)

    ln.byte(0x33, stop=0); ln.idle(2)                  # stop bit low: framing error
    ok = check("framing error: stop bit low", ln.take(), [0x033], ok)
    ln.drive([0] * (20 * 8 * tick)); ln.idle(2)        # a break
    ok = check("a break of 20 bit times", ln.take(), [0x000], ok)
    ln.byte(0xC3); ln.idle(2)
    ok = check("a byte after the break", ln.take(), [0x1C3], ok)

    # loopback: uart_tx on another engine, pin 0 to pin 0, same divider
    tx = Engine(tx_prog, Config.for_program(tx_prog, clkdiv=clkdiv, out_base=0, out_count=1, set_base=0, set_count=1,
                                            side_base=0, out_right=True))
    rx = Line(clkdiv)
    msg = [(i * 73 + 5) & 0xFF for i in range(32)]
    queue = list(msg)
    for _ in range(32 * 12 * 8 * tick + 200 * tick):
        if queue and tx.tx_put(queue[0]):
            queue.pop(0)
        tx.clock(0)
        rx.drive([(tx.out_val & 1) if (tx.out_dir & 1) else 1])
    ok = check("loopback from uart_tx, 32 bytes", rx.take(), [0x100 | b for b in msg], ok)
    return ok


divs = [int(a) for a in sys.argv[1:]] or [12, 155, 53]
ok = all([run(d) for d in divs])
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
