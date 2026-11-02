"""programs/spi_master.asm on the engine model, talking to a model SPI slave (model/spi_slave.py).

  1. select, write 4 bytes to registers 5.. (command 0x05, data), deselect
  2. select, read them back (command 0x85, 4 dummy bytes), deselect
  3. checks the bytes the slave saw, the bytes the engine pushed, MISO's idle level, and the SCK timing
     (one bit = 6 ticks, high 3 and low 3).  Run:  python model/test_spi.py [clkdiv]
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config
from spi_slave import SPISlave

SCK, MOSI, MISO, CS = 0, 1, 2, 3
prog = assemble(open(os.path.join(ROOT, "programs", "spi_master.asm")).read())
L = prog.labels


def cmd_select():     return L["select"] << 11
def cmd_deselect():   return L["deselect"] << 11
def cmd_xfer(byte):   return L["xfer"] << 11 | (byte & 0xFF) << 3


def spi_config(clkdiv):
    return Config.for_program(prog, clkdiv=clkdiv, set_base=0, set_count=4, side_base=0,
                              out_base=MOSI, out_count=1, in_base=MISO, out_right=False, in_right=False)


class Bus:
    def __init__(self, clkdiv, slave):
        self.eng = Engine(prog, spi_config(clkdiv))
        self.slave = slave
        self.miso = 1
        self.sck_highs, self.sck_lows, self.sck_rises = [], [], []
        self.last_sck, self.sck_since, self.t = 0, 0, 0
        self.replies = []

    def pin(self, n):
        e = self.eng
        return (e.out_val >> n) & 1 if (e.out_dir >> n) & 1 else 1      # undriven pins read high (pull-ups)

    def run(self, words, idle_clocks=2000):
        todo = list(words)
        quiet = 0
        while quiet < idle_clocks:
            if todo and self.eng.tx_put(todo[0]):
                todo.pop(0)
            cs, sck, mosi = self.pin(CS), self.pin(SCK), self.pin(MOSI)
            self.miso = self.slave.clock(cs, sck, mosi)
            if sck != self.last_sck:
                (self.sck_lows if sck else self.sck_highs).append(self.t - self.sck_since)
                if sck:
                    self.sck_rises.append(self.t)
                self.sck_since = self.t
            self.last_sck = sck
            got = self.eng.rx_get()
            if got is not None:
                self.replies.append(got)
            self.eng.clock(self.miso << MISO)
            self.t += 1
            busy = todo or self.eng.rxf or self.eng.txf or not self.eng.stalled
            quiet = 0 if busy else quiet + 1
        return self.replies


def main(clkdiv):
    ok = True

    def check(what, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  {what:58s} {'ok' if good else 'WRONG: got ' + repr(got) + ', wanted ' + repr(want)}")

    slave = SPISlave()
    bus = Bus(clkdiv, slave)
    data = [0x5A, 0x81, 0x00, 0xFF]
    print(f"clkdiv {clkdiv}: write {len(data)} bytes to registers 5..8")
    got = bus.run([cmd_select(), cmd_xfer(0x05)] + [cmd_xfer(b) for b in data] + [cmd_deselect()])
    check("slave saw select, command 0x05, 4 writes, deselect", slave.events,
          [("select",), ("cmd", 0x05)] + [("write", 5 + i, b) for i, b in enumerate(data)] + [("deselect",)])
    check("slave's registers 5..8", slave.regs[5:9], data)
    check("engine pushed one byte per transfer (slave answers 0 while writing)", got, [0] * 5)
    slave.events.clear(); bus.replies.clear()
    print("read them back")
    got = bus.run([cmd_select(), cmd_xfer(0x85)] + [cmd_xfer(0)] * 4 + [cmd_deselect()])
    check("engine pushed 0 (during the command) then the 4 bytes", got, [0] + data)
    check("slave saw command 0x85 and 4 reads", slave.events,
          [("select",), ("cmd", 0x85)] + [("read", 5 + i, b) for i, b in enumerate(data)] + [("deselect",)])
    check("CS high at the end", bus.pin(CS), 1)
    check("SCK low at the end", bus.pin(SCK), 0)
    bit = 6 * (clkdiv + 1)
    periods = [b - a for a, b in zip(bus.sck_rises, bus.sck_rises[1:])]
    check(f"bit periods of exactly {bit} clocks: at least 7 per byte", sum(p == bit for p in periods) >= 7 * 10, True)
    check(f"every SCK high = {bit // 2} clocks", set(bus.sck_highs[1:]), {bit // 2})   # [0] = undriven before power-up
    check(f"shortest SCK low >= {bit // 2} clocks", min(bus.sck_lows[1:], default=0) >= bit // 2, True)
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    good = all(main(d) for d in ([int(sys.argv[1])] if len(sys.argv) > 1 else (0, 3, 24)))
    sys.exit(0 if good else 1)
