"""programs/dali_tx.asm and programs/dali_rx.asm on the engine model, with a model DALI control gear on the bus.

Engine A runs dali_tx on engine pin 8 (the NPN base: pin high = bus shorted), engine B runs dali_rx on engine pin 0 (the bus
voltage: high = 1). The bus is high unless A's transistor or the gear shorts it. The gear (class Gear) is an independent
decoder: it finds every forward frame from the bus edges, resyncing on each mid-bit edge and measuring how far each bit
period is from 833.3 us; keeps an arc power level; and answers the queries with a backward frame after a settling time,
with its own half-bit timing (0, -5 or +5 % off: the standard allows 10 %), each answer starting at a different phase of the
engine's tick (nine steps across it), optionally with a coding violation in one bit.
For every exchange the host (this test) arms B with the window (96 ticks = 10 ms), pushes the frame to A and takes the one
word B pushes, checking it against what the gear should have answered:
  broadcast DAPC 254 (no answer: 0x000), QUERY ACTUAL LEVEL (0x1FE, nine times: every phase), DAPC 127, QUERY LEVEL (0x17F), QUERY DEVICE TYPE
  (0x106, LED), QUERY STATUS (0x144: lamp on, no short address), OFF, QUERY LEVEL (0x100), QUERY STATUS (0x140),
  QUERY LAMP FAILURE (answered "no" = no frame: 0x000), QUERY LEVEL to short address 5 where there is no gear (0x000),
  then answers with a coding violation (both halves of one bit the same level): 0x200 | the bits read so far, and a clean
  query after each to show the receiver recovers. Two DAPC words queued together must go out 9.17 ms apart (the gap loop).
Also checked: every forward frame decoded by the gear is the word sent, with bit periods within 0.5 % and the start bit's
first half within 2 % of 416.7 us.
Run:  python model/test_dali.py [12|50 ...]   (default 12 50: the kit at clkdiv 1249, the ASIC at 5207. 12 runs the gear
at 0 and +-5 % with the answer 5.5 ms after the frame, then 2.9 and 9.2 ms; 50 runs one full sequence: the model is slow).
"quick" runs only the short sequence at 0 % (for the planted-bug check).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

TX_PIN, RX_PIN = 8, 0
WINDOW = 96                                       # ticks of a bit/8: 10 ms
tx_prog = assemble(open(os.path.join(ROOT, "programs", "dali_tx.asm")).read())
rx_prog = assemble(open(os.path.join(ROOT, "programs", "dali_rx.asm")).read())
FAULT = rx_prog.labels["fault"]

DEVICE_TYPE_LED = 6


class Gear:
    """A DALI control gear on the bus: decodes forward frames from the bus edges, answers queries."""
    def __init__(self, clk_hz, err=0.0, settle_ms=5.5):
        self.bit = clk_hz / 1200.0                 # clocks per bit, as sent by the controller
        self.tx_hb = self.bit / 2 * (1 + err)      # this gear's own half bit
        self.settle = clk_hz * settle_ms / 1000
        self.level = 0
        self.violate = None                        # (bit index 0..7 or 'start', 'HH' or 'LL') for the next answer
        self.state = "idle"; self.prev = 1
        self.frames = []                           # (addr, data, worst bit-period error, start-half error, end clock)
        self.errors = []
        self.shorts = []                           # [start, end) clocks when this gear shorts the bus
        self.tx_end = -1
        self.answers = []                          # (byte, start clock)
        self.f = self.last_m = 0; self.bits = []

    def shorting(self, t):
        while self.shorts and t >= self.shorts[0][1]:
            self.shorts.pop(0)
        return bool(self.shorts) and self.shorts[0][0] <= t < self.shorts[0][1]

    def observe(self, t, bus):
        """Called every clock with the bus level. Decodes forward frames when not transmitting."""
        if t < self.tx_end:
            self.prev = bus; return
        edge = bus != self.prev
        self.prev = bus
        if self.state == "idle":
            if edge and bus == 0:
                self.f = t; self.state = "start"
        elif self.state == "start":
            if edge and bus == 1:
                half = (t - self.f) / self.bit
                if not 0.3 < half < 0.7:
                    self.errors.append((t, f"start half {half:.2f} bit")); self.state = "idle"; return
                self.start_err = abs(half - 0.5) / 0.5
                self.bits = [1]; self.worst = 0.0; self.last_m = t; self.state = "bit"
            elif t - self.f > 1.4 * self.bit:
                self.errors.append((t, "bus held low")); self.state = "idle"
        elif self.state == "bit":
            since = t - self.last_m
            if edge and since >= 0.6 * self.bit:
                self.bits.append(bus)
                self.worst = max(self.worst, abs(since - self.bit) / self.bit)
                self.last_m = t
            elif not edge and since > 1.4 * self.bit:
                self.state = "idle"
                end = self.last_m + 0.5 * self.bit
                if bus == 1 and len(self.bits) == 17:
                    addr = int("".join(map(str, self.bits[1:9])), 2); data = int("".join(map(str, self.bits[9:17])), 2)
                    self.frames.append((addr, data, self.worst, self.start_err, end))
                    self.command(addr, data, end)
                else:
                    self.errors.append((t, f"{len(self.bits)} bits, bus {bus}"))

    def command(self, addr, data, end):
        answer = None
        if addr == 0xFE:                           # broadcast, S = 0: direct arc power
            if data != 255: self.level = data
        elif addr == 0xFF:                         # broadcast command
            if data == 0x00: self.level = 0                                   # OFF
            elif data == 0xA0: answer = self.level                            # QUERY ACTUAL LEVEL
            elif data == 0x90: answer = 0x40 | (0x04 if self.level else 0)    # QUERY STATUS: no short address; lamp on
            elif data == 0x99: answer = DEVICE_TYPE_LED                       # QUERY DEVICE TYPE
            # 0x92 QUERY LAMP FAILURE and anything else: "no", so no backward frame
        # a short address (bit 7 clear): nobody here
        if answer is not None:                     # each answer starts at a different phase of the engine's tick:
            self.send(answer, end + self.settle + len(self.answers) % 9 * self.bit / 72)   # 9 steps across the 1/8-bit tick

    def send(self, byte, t0):
        """Backward frame: start bit then 8 bits MSB first, a 1 = short the bus in the first half, a 0 in the second."""
        hb = self.tx_hb
        seq = [("start", 1)] + [(i, (byte >> (7 - i)) & 1) for i in range(8)]
        for n, (idx, b) in enumerate(seq):
            t = t0 + 2 * n * hb
            halves = (1, 0) if b else (0, 1)          # which halves are shorted
            if self.violate and self.violate[0] == idx:
                halves = (0, 0) if self.violate[1] == "HH" else (1, 1)
            for h, s in enumerate(halves):
                if s: self.shorts.append((t + h * hb, t + (h + 1) * hb))
        self.violate = None
        self.tx_end = t0 + 18 * hb + self.bit
        self.answers.append((byte, t0))


class Bus:
    def __init__(self, clk_hz, err=0.0, settle_ms=5.5):
        self.clk_hz = clk_hz
        div = round(clk_hz / 9600) - 1
        self.div = div
        self.a = Engine(tx_prog, Config.for_program(tx_prog, clkdiv=div, out_base=TX_PIN, out_count=1, set_base=TX_PIN, set_count=1, out_right=False))
        self.b = Engine(rx_prog, Config.for_program(rx_prog, clkdiv=div, in_base=RX_PIN, jmp_pin=RX_PIN, in_right=False, fault_addr=FAULT))
        self.gear = Gear(clk_hz, err, settle_ms)
        self.t = 0
        self.got = []                               # (clock, word) from B
        self.bus = 1

    def clock(self):
        a = self.a
        tx = (a.out_val >> TX_PIN) & 1 if (a.out_dir >> TX_PIN) & 1 else 0
        bus = 0 if (tx or self.gear.shorting(self.t)) else 1
        self.bus = bus
        self.gear.observe(self.t, bus)
        w = self.b.rx_get()
        if w is not None:
            self.got.append((self.t, w))
        a.clock(0)
        self.b.clock(bus << RX_PIN)
        self.t += 1

    def run_ms(self, ms):
        for _ in range(int(self.clk_hz * ms / 1000)):
            self.clock()

    def exchange(self, word, arm=True, limit_ms=60):
        """Arm B, push the frame to A, run until B answers (or limit). Returns B's word (None if none)."""
        if arm:
            assert self.b.tx_put(WINDOW)
        assert self.a.tx_put(word)
        n0 = len(self.got)
        for _ in range(int(self.clk_hz * limit_ms / 1000)):
            self.clock()
            if len(self.got) > n0:
                break
        self.run_ms(12)                             # the rest of any answer, and A's 9.5 ms gap
        return self.got[n0][1] if len(self.got) > n0 else None

    def ms(self, clocks):
        return clocks / self.clk_hz * 1000


def run(mhz, err, settle_ms, full=True):
    clk_hz = mhz * 1e6
    bus = Bus(clk_hz, err, settle_ms)
    ok = True
    print(f"-- {mhz} MHz, clkdiv {bus.div} (tick {(bus.div + 1) / clk_hz * 1e6:.2f} us): gear {err * 100:+.0f} %, answers after {settle_ms} ms")

    def check(what, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"  {what:70s} {'ok' if good else 'WRONG'} {detail}")

    def frame(name, word, want):
        got = bus.exchange(word)
        check(f"{name}: {word:04X} -> {'%04X' % got if got is not None else 'nothing'}", got == want,
              f"(wanted {want:04X})" if got != want else "")

    bus.run_ms(3)
    check("bus idle high, B silent, A's pin driven low", bus.bus == 1 and bus.got == [] and (bus.a.out_dir >> TX_PIN) & 1 and not (bus.a.out_val >> TX_PIN) & 1)
    frame("broadcast DAPC 254", 0xFEFE, 0x000)
    frame("QUERY ACTUAL LEVEL", 0xFFA0, 0x1FE)
    if full:
        for k in range(8):                        # the same answer at every phase of the tick (nine answers, nine phases)
            frame(f"QUERY ACTUAL LEVEL, phase {k + 1} of 9", 0xFFA0, 0x1FE)
    frame("broadcast DAPC 127", 0xFE7F, 0x000)
    frame("QUERY ACTUAL LEVEL", 0xFFA0, 0x17F)
    frame("QUERY DEVICE TYPE (6 = LED)", 0xFF99, 0x106)
    frame("QUERY STATUS (lamp on, no short address)", 0xFF90, 0x144)
    frame("OFF", 0xFF00, 0x000)
    frame("QUERY ACTUAL LEVEL", 0xFFA0, 0x100)
    if full:
        frame("QUERY STATUS (lamp off)", 0xFF90, 0x140)
        frame("QUERY LAMP FAILURE: the gear says no (no frame)", 0xFF92, 0x000)
        frame("QUERY ACTUAL LEVEL to short address 5: nobody there", 0x0BA0, 0x000)
        frame("broadcast DAPC 85", 0xFE55, 0x000)
        for idx, kind in (("start", "LL"), (0, "HH"), (0, "LL"), (3, "HH"), (3, "LL"), (7, "HH"), (7, "LL")):
            bus.gear.violate = (idx, kind)
            k = 0 if idx == "start" else idx
            want = 0x200 | (1 << k) | (0x55 >> (8 - k) if k else 0)
            frame(f"QUERY LEVEL, answer 55 with bit {idx} sent {kind}: framing error", 0xFFA0, want)
            frame("QUERY ACTUAL LEVEL again, clean", 0xFFA0, 0x155)
        # two frames queued: A must hold the bus idle 9.17 ms between them (not armed: B would take the second as an answer)
        n = len(bus.gear.frames)
        assert bus.a.tx_put(0xFE10); bus.run_ms(0.1); assert bus.a.tx_put(0xFE20)
        bus.run_ms(50)
        fr = bus.gear.frames[n:]
        gap = bus.ms(fr[1][4] - fr[0][4]) - 17 * 833.33 / 1000 if len(fr) == 2 else 0
        check("two queued DAPC frames both decoded, 9.17 ms or more between them", len(fr) == 2 and fr[0][:2] == (0xFE, 0x10) and fr[1][:2] == (0xFE, 0x20) and gap >= 9.17, f"gap {gap:.2f} ms")
        frame("QUERY ACTUAL LEVEL after the pair", 0xFFA0, 0x120)
    g = bus.gear
    worst = max(f[2] for f in g.frames); worst_start = max(f[3] for f in g.frames)
    check(f"gear decoded {len(g.frames)} forward frames, no errors", not g.errors, str(g.errors[:3]))
    check("every bit period within 0.5 % of 833.3 us, start half within 2 %", worst < 0.005 and worst_start < 0.02, f"worst {worst * 100:.3f} % and {worst_start * 100:.2f} %")
    return ok


def main(mhzs, quick=False):
    ok = True
    for mhz in mhzs:
        if quick:
            ok &= run(mhz, 0.0, 5.5, full=False)
        elif mhz < 20:
            ok &= run(mhz, 0.0, 5.5)
            ok &= run(mhz, -0.05, 5.5)
            ok &= run(mhz, +0.05, 5.5)
            ok &= run(mhz, 0.0, 2.9, full=False)
            ok &= run(mhz, 0.0, 9.2, full=False)
        else:
            ok &= run(mhz, +0.05, 5.5)
    print("PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "quick"]
    sys.exit(0 if main([float(a) for a in args] or [12, 50], quick="quick" in sys.argv) else 1)
