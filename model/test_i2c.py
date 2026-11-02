"""programs/i2c_master.asm on the engine model, talking to a model I2C slave (model/i2c_slave.py).

  1. writes 4 bytes to the slave's registers at pointer 3 (START, addr+W, pointer, data..., STOP)
  2. reads them back with a repeated START (START, addr+W, pointer, START, addr+R, 4 bytes, NAK, STOP)
  3. addresses a device that isn't there and checks the engine reports the NAK
  4. does 1 and 2 again with a slave that stretches the clock after every ACK
and checks every ACK bit the engine reports, the slave's log of the transaction, the bytes read back,
and the SCL period (one bit = 10 ticks). Engine B runs programs/i2c_sniff.asm on the same bus and must report
every byte with its ACK.  Run:  python model/test_i2c.py [clkdiv]
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config
from i2c_slave import I2CSlave

SCL, SDA = 0, 1
prog = assemble(open(os.path.join(ROOT, "programs", "i2c_master.asm")).read())
sniff = assemble(open(os.path.join(ROOT, "programs", "i2c_sniff.asm")).read())
L = prog.labels


def cmd_start():      return L["start"] << 11
def cmd_stop():       return L["stop"] << 11
def cmd_send(byte):   return L["send"] << 11 | (byte & 0xFF) << 3
def cmd_recv(ack):    return L["recv"] << 11 | (1 << 10 if ack else 0)


def i2c_config(clkdiv):
    return Config.for_program(prog, clkdiv=clkdiv, set_base=SDA, set_count=1, side_base=SCL,
                              out_base=SDA, out_count=1, in_base=SDA, out_right=False, in_right=False)


class Bus:
    """Open-drain SDA and SCL with pull-ups. Runs the engine, the watcher and the slave clock by clock."""
    def __init__(self, clkdiv, slave):
        self.eng = Engine(prog, i2c_config(clkdiv))
        self.watcher = Engine(sniff, Config.for_program(sniff, in_base=0, jmp_pin=SDA, out_right=True, in_right=False))   # engine B
        self.seen = []                                     # what the watcher pushed: byte << 1 | ack
        self.slave = slave
        self.slave_low = False
        self.slave_scl_low = False
        self.scl_rises = []
        self.scl_highs, self.scl_lows = [], []            # every SCL high and low time, in clocks
        self.last_scl = 1
        self.scl_since = 0
        self.t = 0
        self.replies = []

    def levels(self):
        e = self.eng
        scl = 0 if ((e.out_dir >> SCL) & 1 and not (e.out_val >> SCL) & 1) or self.slave_scl_low else 1
        sda = 0 if ((e.out_dir >> SDA) & 1 and not (e.out_val >> SDA) & 1) or self.slave_low else 1
        return scl, sda

    def run(self, words, idle_clocks=2000):
        """Feed the command words to the engine, run until it has been idle a while, collect its pushes."""
        todo = list(words)
        quiet = 0
        while quiet < idle_clocks:
            if todo and self.eng.tx_put(todo[0]):
                todo.pop(0)
            scl, sda = self.levels()
            self.slave_low, self.slave_scl_low = self.slave.clock(scl, sda)
            scl, sda = self.levels()                      # the slave's reply is on the wire at once
            if scl != self.last_scl:
                (self.scl_rises if scl else []).append(self.t)
                (self.scl_lows if scl else self.scl_highs).append(self.t - self.scl_since)
                self.scl_since = self.t
            self.last_scl = scl
            got = self.eng.rx_get()
            if got is not None:
                self.replies.append(got)
            self.eng.clock((scl << SCL) | (sda << SDA))
            got = self.watcher.rx_get()
            if got is not None:
                self.seen.append(got)
            self.watcher.clock((scl << SCL) | (sda << SDA))
            self.t += 1
            busy = todo or self.eng.rxf or self.eng.txf or not self.eng.stalled
            quiet = 0 if busy else quiet + 1
        return self.replies


def main(clkdiv, stretch=0):
    ok = True

    def check(what, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  {what:58s} {'ok' if good else 'WRONG: got ' + repr(got) + ', wanted ' + repr(want)}")

    slave = I2CSlave(address=0x50, stretch=stretch)
    bus = Bus(clkdiv, slave)
    data = [0xA5, 0x3C, 0x00, 0xFF]
    if stretch:
        print(f"clkdiv {clkdiv}, slave stretching SCL by {stretch} clocks after every ACK")
    # 1. write
    words = [cmd_start(), cmd_send(0x50 << 1), cmd_send(3)] + [cmd_send(b) for b in data] + [cmd_stop()]
    acks = bus.run(words)
    print(f"  write {len(data)} bytes to register 3")
    check("every byte acked (the engine's ACK bits)", acks, [0] * (2 + len(data)))
    check("slave saw START, addr+W, pointer, data, STOP", slave.events,
          [("start", None), ("addr", 0xA0), ("pointer", 3)] + [("write", b) for b in data] + [("stop", None)])
    check("slave's registers 3..6", slave.regs[3:7], data)
    check("engine B (watcher) saw the same bytes, all acked", bus.seen, [b << 1 for b in [0xA0, 3] + data])
    bus.seen.clear()
    # 2. read back with a repeated START
    slave.events.clear(); bus.replies.clear()
    words = [cmd_start(), cmd_send(0x50 << 1), cmd_send(3), cmd_start(), cmd_send(0x50 << 1 | 1)]
    words += [cmd_recv(ack=True)] * 3 + [cmd_recv(ack=False), cmd_stop()]
    got = bus.run(words)
    print("read them back (repeated START)")
    check("3 ACKs then the 4 bytes", got, [0, 0, 0] + data)
    check("slave saw the read sequence", slave.events,
          [("start", None), ("addr", 0xA0), ("pointer", 3), ("start", None), ("addr", 0xA1)]
          + [("read", b) for b in data] + [("nak", None), ("stop", None)])
    check("watcher saw the read, last byte NAKed", bus.seen, [b << 1 for b in [0xA0, 3, 0xA1] + data[:-1]] + [data[-1] << 1 | 1])
    bus.seen.clear()
    if stretch:
        print("PASS" if ok else "FAIL")
        return ok
    # 3. nobody home
    slave.events.clear(); bus.replies.clear()
    got = bus.run([cmd_start(), cmd_send(0x23 << 1), cmd_stop()])
    print("address 0x23 (no such device)")
    check("engine reports NAK (1)", got, [1])
    check("slave stayed quiet", slave.events, [("start", None), ("addr", 0x46), ("stop", None)])
    check("watcher saw the NAKed address", bus.seen, [0x46 << 1 | 1])
    # SCL timing: 10 ticks per bit within a byte; every high and low at least 5 ticks (the standard's minimums)
    periods = [b - a for a, b in zip(bus.scl_rises, bus.scl_rises[1:])]
    bit = 10 * (clkdiv + 1)
    nbytes = 6 + 7 + 1                                     # bytes sent or received over the three transactions
    check(f"at least {8 * nbytes} bit periods of exactly {bit} clocks", sum(p == bit for p in periods) >= 8 * nbytes, True)
    check(f"shortest SCL high >= {bit // 2} clocks", min(bus.scl_highs[1:]) >= bit // 2, True)
    check(f"shortest SCL low >= {bit // 2} clocks", min(bus.scl_lows) >= bit // 2, True)
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    # master dividers 2, 4, 49: below 2 the input synchroniser stretches SCL's high time by a tick (see the program),
    # and the watcher (at divider 0) needs an SCL period of at least 20 of its ticks
    divs = [int(sys.argv[1])] if len(sys.argv) > 1 else (2, 4, 49)
    good = all(main(d) for d in divs) and all(main(d, stretch=s) for d in divs for s in (7, 300))
    sys.exit(0 if good else 1)
