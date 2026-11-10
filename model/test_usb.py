"""Low-speed USB on engine 0 (private/usb_ls.md, build order step 4): the engine model's USB mode against the reference
(model/usb_line.py), then programs/usb_host.asm and the host logic (model/usb_host.py) with the model keyboard.

1. Transmit, clock for clock: random packets (tokens, data with 0xFF runs, handshakes, raw bytes with six 1s across
   word ends and just before the EOP, odd byte counts) and keep-alives. Every clock from the first driven one to the
   release must equal the reference symbols, each half-bit SERDIV + 1 clocks plus the SERFRAC carry worked out
   independently ((k + 1) x SERFRAC div 256 - k x SERFRAC div 256), both pins driven throughout, let go after the
   EOP's J. SERDIV 12 + SERFRAC 85 (1,500,146 bit/s) and 12 / 0, buffers of 1024 and 64 words.
2. Receive: the same kinds of packet sent at the device's rate -1.5 %, 0, +1.5 %, random phase, D- up to 2 clocks
   either side of D+ (SE0 or SE1 blips at every crossing), edges +-1.5 clocks: the ring holds the packet from the PID,
   USBSTAT says PID, checks, bytes and the packet count, and "ACK it" (status bit 10) is set exactly for good DATA.
   Faults, each flagged and never "ACK it": seven 1s, a bad PID check, a bad CRC16, a bit too many, SE1. A lone SE0 and
   a short pulse start nothing. The widest rate offset with every packet right is reported.
3. The whole thing: usb_host.asm (29 words) on the engine model, the host logic through a port that pushes and reads
   one word per 3.2 us (5 MHz SPI), the model keyboard at -1.5 % and +1.5 % with crossings and jitter: bus reset
   (a drive-low program, 10 ms), enumeration (descriptors checked against the model's), the LEDs in a scripted order,
   the scripted keys read back line by line with NAKs, bad reports and missed ACKs; the chip's ACKs 2 to 7.5 bit
   times after the keyboard's EOP (measured by the keyboard, which also checks rate, EOP, gaps, keep-alives and
   toggles); attach and detach seen in USBSTAT [9:8]; keep-alives through 3.5 ms of idle.
4. USB mode off by default: status bit 10 reads 0 and the directions are the program's (cosim covers the rest).
`python model/test_usb.py plant` instead runs planted bugs, each of which must fail.
Run:  python model/test_usb.py [plant]
"""
import importlib.util, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import usb_line as U
import engine as E
import usb_host as H
from asm import assemble
from usb_kbd import UsbKeyboard, Tx, DEVICE_DESC, CONFIG_DESC, REPORT_DESC, VID, PID
from test_usb_kbd import script_reports, read_keys, LEDS

CLK = 40_000_000
PN = CLK / 1.5e6
SRC = open(os.path.join(ROOT, "programs", "usb_host.asm")).read()
SENDER = ".wrap_target\n pull block\n mov ser, osr\n wait 0, ser\n.wrap\n"
IDLE_SRC = "top:\n    jmp    top\n"
RESET_SRC ="    set    pindirs, 3\nhold:\n    set    pins, 0\n    jmp    hold\n"
fails = []
QUIET = False


def check(what, ok, info=""):
    if not QUIET or not ok:
        print(f"{'ok:  ' if ok else 'FAIL:'} {what}" + (f": {info}" if info else ""))
    if not ok:
        fails.append(what)
    return ok


def usb_engine(prog, depth=1024, serdiv=12, serfrac=85, **kw):
    p = prog if hasattr(prog, "words") else assemble(prog)
    cfg = E.Config.for_program(p, ser=True, ser_depth=depth, ser_en=True, usb=True, serdiv=serdiv, serfrac=serfrac,
                               rxgap=27, rx_pin=0, out_base=0, out_right=True, in_right=True, crc_unit=False, **kw)
    eng = E.Engine(p, cfg)
    eng.clock(0x2, mode_wr=2)                     # a keyed SERCFG write: full duplex
    return eng


def pins_of(bus):
    return bus[0] | bus[1] << 1


# ---- 1. transmit
def expected_wave(syms, serdiv, serfrac):
    out, acc, k = [], 0, 0
    for s in syms:
        for _ in range(2):
            carry = ((k + 1) * serfrac) // 256 - (k * serfrac) // 256
            out += [U.LEVELS[s]] * (serdiv + 1 + carry)
            k += 1
    return out


def send_one(pkt, depth, serdiv, serfrac, keepalive=False):
    """Returns (the clocks while driven as (D+, D-), whether both pins were driven throughout, words left)."""
    eng = usb_engine(SENDER, depth, serdiv, serfrac)
    words = [0xFFFF] if keepalive else [len(pkt) + 1] + U.words_of(pkt)
    got, alldir = [], True
    for _ in range(200 * (len(pkt) + 3) * (serdiv + 3)):
        if words and eng.tx_put(words[0]):
            words.pop(0)
        d = eng.dirs_out & 3
        if d == 0 and got:
            break
        if d:
            alldir &= d == 3
            got.append((eng.pins_out & 1, eng.pins_out >> 1 & 1))
        eng.clock(pins_of((0, 1)))
    return got, alldir, len(eng.txf)


def packets(rnd, n):
    out = [U.handshake(U.PID_ACK), U.token(U.PID_IN, 1, 1), U.data(U.PID_DATA0, b"\xff" * 8), bytes([0xFC]),
           b"\xff\xff\xff", bytes([0x3F, 0xFF]), U.data(U.PID_DATA1), U.data(U.PID_DATA1, b"\x7f")]
    while len(out) < n:
        k = rnd.randrange(4)
        if k == 0:
            out.append(U.token(rnd.choice([U.PID_IN, U.PID_OUT, U.PID_SETUP]), rnd.randrange(128), rnd.randrange(16)))
        elif k == 1:
            out.append(U.data(rnd.choice([U.PID_DATA0, U.PID_DATA1]),
                              bytes(rnd.choice([0xFF, 0xFE, 0x7F, rnd.getrandbits(8)]) for _ in range(rnd.randrange(9)))))
        elif k == 2:
            out.append(U.handshake(rnd.choice([U.PID_ACK, U.PID_NAK, U.PID_STALL])))
        else:
            out.append(bytes(rnd.choice([0xFF, rnd.getrandbits(8)]) for _ in range(rnd.randrange(1, 12))))
    return out


def test_transmit(n=60):
    rnd = random.Random(11)
    for depth, serdiv, serfrac in ((1024, 12, 85), (64, 12, 85), (1024, 12, 0)):
        bad = []
        for pkt in packets(rnd, n):
            got, alldir, left = send_one(pkt, depth, serdiv, serfrac)
            want = expected_wave(U.encode(pkt), serdiv, serfrac)
            if got != want or not alldir or left:
                i = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
                bad.append(f"{pkt.hex()}: {len(got)} vs {len(want)} clocks, first difference at {i}")
        got, alldir, _ = send_one(b"", depth, serdiv, serfrac, keepalive=True)
        if got != expected_wave(U.keepalive(), serdiv, serfrac) or not alldir:
            bad.append(f"keep-alive: {got[:3]}... {len(got)} clocks")
        check(f"transmit, {depth} words, SERDIV {serdiv} SERFRAC {serfrac}: {n} packets and a keep-alive clock for "
              f"clock", not bad, "; ".join(bad[:2]))
    syms = U.encode(bytes(range(8)))
    clocks = len(expected_wave(syms, 12, 85))
    check("SERFRAC 85: the rate", True, f"{len(syms)} bits in {clocks} clocks, {CLK * len(syms) / clocks:,.0f} bit/s")


# ---- 2. receive
def receive_one(syms, rate, skew, jitter, rnd, depth=1024):
    eng = usb_engine(IDLE_SRC, depth)
    eng.clock(pins_of((0, 1)), arm=True)
    tx = Tx(syms, 20 + rnd.random() * PN, PN * (1 + rate), skew, jitter, rnd)
    t = 2
    while t < tx.end + 3 * PN:
        eng.clock(pins_of(tx.levels(t) or (0, 1)))
        t += 1
    words = []
    for _ in range(40):
        eng.clock(pins_of((0, 1)), bpop=True)
        if eng.bpopped is not None:
            words.append(eng.bpopped)
    return eng, words


def expect_rx(pkt, nbits=None, serr=False, se1=False):
    nbits = 8 * len(pkt) if nbits is None else nbits
    pid = pkt[0] if pkt else 0
    pid_ok = nbits >= 8 and U.pid_ok(pid)
    crc_ok = nbits >= 24 and nbits % 8 == 0 and U.crc16_reg(pkt[1:]) == U.CRC16_RESIDUE
    bad = nbits % 8 != 0 or se1
    stat = ((pid & 15) | pid_ok << 4 | crc_ok << 5 | serr << 6 | bad << 7 | min(15, nbits // 8) << 10 | 1 << 14
            | 1 << 8)                                                   # line J after the packet
    ack = pid_ok and (pid & 15) in (U.PID_DATA0, U.PID_DATA1) and crc_ok and not serr and not bad
    return stat, ack


def words_le(b):
    b = bytes(b) + b"\0" * (len(b) % 2)
    return [b[i] | b[i + 1] << 8 for i in range(0, len(b), 2)]


def test_receive():
    rnd = random.Random(21)
    pk = packets(rnd, 40)
    for depth in (1024, 64):
        bad, n = [], 0
        for rate in (-0.015, 0.0, 0.015):
            for skew, jitter in ((0.0, 0.0), (2.0, 1.5), (-2.0, 1.5)):
                for pkt in pk:
                    eng, words = receive_one(U.encode(pkt), rate, skew, jitter, rnd, depth)
                    stat, ack = expect_rx(pkt)
                    n += 1
                    if not (eng.rx_ready and eng.usbstat == stat and eng.usb_ack == ack and words == words_le(pkt)):
                        bad.append(f"{pkt.hex()} rate {rate} skew {skew}: ready {eng.rx_ready} stat "
                                   f"{eng.usbstat:04x}/{stat:04x} ack {eng.usb_ack}/{ack} words "
                                   f"{[hex(w) for w in words]}")
        check(f"receive, {depth} words: {n} packets at -1.5/0/+1.5 %, crossings and jitter", not bad,
              "; ".join(bad[:2]))
    print("-- receive faults")
    good = U.data(U.PID_DATA0, b"\xff\xff\x00\x81")
    bits = U.stuff(U.bits_lsb(bytes([U.SYNC]) + good))
    k = next(i for i in range(6, len(bits)) if bits[i - 6:i] == [1] * 6) # the first stuff bit
    cases = [("seven 1s (a stuff bit missing)", U.nrzi(bits[:k] + bits[k + 1:]) + U.EOP, None, True, False),
             ("a bad PID check", U.encode(bytes([0x33]) + good[1:]), bytes([0x33]) + good[1:], False, False),
             ("a bad CRC16", U.encode(good[:2] + bytes([good[2] ^ 8]) + good[3:]),
              good[:2] + bytes([good[2] ^ 8]) + good[3:], False, False),
             ("a bit too many", U.nrzi(bits + [0]) + U.EOP, None, False, False)]
    for name, syms, pkt, serr, _ in cases:
        eng, words = receive_one(syms, 0.0, 0.0, 0.0, rnd)
        st = eng.usbstat
        if pkt is not None:
            stat, ack = expect_rx(pkt)
            ok = st == stat and not eng.usb_ack and not ack
        elif serr:
            ok = bool(st >> 6 & 1) and not eng.usb_ack
        else:
            ok = bool(st >> 7 & 1) and not (st >> 5 & 1) and not eng.usb_ack
        check(f"receive fault: {name}", ok and eng.rx_ready, f"USBSTAT {st:04x}")
    syms = U.encode(good)
    syms[20] = U.SE1
    eng, _ = receive_one(syms, 0.0, 0.0, 0.0, rnd)
    check("receive fault: SE1 in the packet", eng.rx_ready and bool(eng.usbstat >> 7 & 1) and not eng.usb_ack,
          f"USBSTAT {eng.usbstat:04x}")
    for name, syms in (("a lone SE0 (keep-alive)", U.keepalive()), ("a short K pulse", [U.K, U.J, U.J, U.J])):
        eng, words = receive_one(syms, 0.0, 0.0, 0.0, rnd)
        check(f"receive: {name} starts nothing", not eng.rx_ready and not words and eng.rx_state != E.RX_DATA,
              f"state {eng.rx_state}")
    # the margin: the widest rate offset with 20 random packets all right (crossings and jitter as above)
    margin = 0.0
    for r in [x / 1000 for x in range(5, 80, 5)]:
        okall = all(receive_one(U.encode(p), s * r, 2.0, 1.5, rnd)[0].usbstat == expect_rx(p)[0]
                    for p in pk[:20] for s in (-1, 1))
        if not okall:
            break
        margin = r
    check("receive margin at least +-3 %", margin >= 0.03, f"every packet right up to +-{margin * 100:.1f} %")


# ---- 3. the chip as host
class ChipPort:
    """The chip: usb_host.asm on the engine model, the keyboard on the pins, the host's SPI at one word a 3.2 us."""

    def __init__(self, kbd, src=SRC, depth=1024, reset_us=10_000, spi=128):
        self.kbd, self.prog, self.depth, self.reset_us, self.spi = kbd, assemble(src), depth, reset_us, spi
        lb = self.prog.labels
        self.poll_pcs = {lb["poll"], lb["poll"] + 1, lb["poll"] + 2, lb["idle"]}
        self.eng, self.t, self.errors = None, 0, []
        self.attached = True

    def clock(self, n=1, bpop=False, arm=False):
        for _ in range(n):
            e = self.eng
            d, lv = (e.dirs_out & 3, e.pins_out) if e else (0, 0)
            kd = self.kbd.drive() if self.attached else None
            if d and kd is not None:
                self.errors.append(f"contention at {self.t}")
            if d and d != 3:
                self.errors.append(f"one wire driven at {self.t}")
            bus = (lv & 1, lv >> 1 & 1) if d else (kd if kd is not None else ((0, 1) if self.attached else (0, 0)))
            if self.attached:
                self.kbd.clock(*bus, host=bool(d))
            if e:
                e.clock(pins_of(bus), bpop=bpop, arm=arm)
            bpop = arm = False
            self.t += 1

    def start(self):
        self.eng = usb_engine(self.prog, self.depth, fault_addr=self.prog.labels["drop"])
        self.eng.tx_put(8000)                         # the reply timeout: 200 us; keep-alives about 0.8 ms apart
        self.clock(self.spi)

    def bus_reset(self):
        rp = assemble(RESET_SRC)
        self.eng = E.Engine(rp, E.Config.for_program(rp, set_base=0, set_count=2))
        self.clock(int(self.reset_us * 1e-6 * CLK))
        self.start()
        self.clock(int(100e-6 * CLK))

    def idle(self, us):
        self.clock(int(us * 1e-6 * CLK))

    def transact(self, words):
        e = self.eng
        c0 = e.usbstat >> 14
        self.clock(2 * self.spi)                      # read USBSTAT
        self.clock(self.spi)                          # the burst's command
        for w in words:
            if not e.tx_put(w):
                self.errors.append("transmit ring full")
            self.clock(self.spi)
        for _ in range(4000):                         # read STATUS until the program is back in its poll loop
            self.clock(2 * self.spi)
            if not e.txf and not e.ser_busy and e.pc in self.poll_pcs:
                break
        else:
            self.errors.append("the program did not finish a transaction")
        st = e.usbstat
        self.clock(2 * self.spi)
        if st >> 14 == c0:
            return None                               # no reply
        n = st >> 10 & 15
        raw = []
        for _ in range((n + 1) // 2):
            self.clock(1, bpop=True)
            if e.bpopped is None:
                self.errors.append("RXDATA read with nothing in the ring")
            raw.append(e.bpopped or 0)
            self.clock(self.spi - 1)
        r = H.Reply(st, b"".join(w.to_bytes(2, "little") for w in raw)[:n])
        if not r.ok:
            self.clock(1, arm=True)                   # a bad reply may leave a partial word: empty the ring
        return r


def full_chip(rate, seed, label, src=SRC, quiet=False, reset_us=10_000, keys=True):
    reports, want = script_reports()
    kbd = UsbKeyboard(CLK, rate=rate, seed=seed, script=reports, skew=1.5, jitter=1.0, naks=(0, 2), corrupt=3,
                      deaf=4)
    port = ChipPort(kbd, src, reset_us=reset_us)
    host = H.UsbHost(port)
    bad = []

    def chk(what, got, want_):
        if got != want_:
            bad.append(f"{label}: {what} = {got!r}"[:300] + f", expected {want_!r}"[:200])
        elif not quiet:
            print(f"ok:   {label}: {what}")
    port.start()
    port.clock(200)
    chk("attached: USBSTAT [9:8] reads J", port.eng.usbstat >> 8 & 3, 1)
    port.attached = False
    port.clock(200)
    chk("detached: SE0", port.eng.usbstat >> 8 & 3, 0)
    port.attached = True
    try:
        info = host.enumerate()
        chk("device descriptor", info["device"], DEVICE_DESC)
        chk("VID:PID", (info["vid"], info["pid"]), (VID, PID))
        chk("configuration descriptor", info["config"], CONFIG_DESC)
        chk("strings", (info["manufacturer"], info["product"]), ("ProtocolASIC", "Model keyboard"))
        chk("report descriptor", info["report_desc"], REPORT_DESC)
        chk("address and configuration", (kbd.addr, kbd.config), (1, 1))
        if keys:
            for v in LEDS:
                host.set_leds(v)
            chk("LEDs in order", [l for l in kbd.log if l.startswith("LEDs")], [f"LEDs {v:#04x}" for v in LEDS])
            lines = read_keys(host, len(want))
            chk("keys read back line by line", lines, want)
            if not quiet:
                print("        " + ", ".join(f"{w}:{g}" for w, g in zip(want, lines)))
        ka = kbd.counts["keepalives"]
        port.idle(3500)
        chk("keep-alives through 3.5 ms idle", kbd.counts["keepalives"] - ka >= 3, True)
    except H.UsbError as ex:
        bad.append(f"{label}: {ex}")
    chk("keyboard errors", kbd.errors[:3], [])
    chk("host errors", host.errors[:3], [])
    chk("bench errors", port.errors[:3], [])
    if keys:
        c = kbd.counts
        chk("NAKs, bad reports, missed ACKs and dropped copies all exercised",
            (c["naks"] > 0, c["corrupt"] > 0, c["deaf"] > 0, host.counts["dup"] >= c["deaf"]), (True,) * 4)
    w = kbd.ack_windows
    chk("every ACK 2 to 7.5 bit times after the keyboard's EOP", bool(w) and 2 <= min(w) and max(w) <= 7.5, True)
    if not quiet:
        print(f"        {len(w)} ACKs, {min(w or [0]):.2f} to {max(w or [0]):.2f} bit times after the keyboard's EOP; "
              f"{port.t / CLK * 1e3:.1f} ms simulated; keyboard {kbd.counts}; host {host.counts}")
    return bad


def test_off():
    p = assemble(".wrap_target\n mov x, status\n mov ser, x\n.wrap\n")
    eng = E.Engine(p, E.Config.for_program(p, ser=True, ser_depth=1024, ser_en=True, out_count=2))
    eng.clock(0, mode_wr=2)
    eng.usb_ack = True                                # even with the flag set, USB mode off shows nothing
    for _ in range(50):
        eng.clock(0)
    check("USB mode off: status bit 10 is 0, the directions are the program's",
          not (eng.x >> 10 & 1) and eng.dirs_out == eng.out_dir and not eng.usb_on)


def run(quick=False, src=SRC, reset_us=10_000):
    print("-- 1. transmit")
    test_transmit(20 if quick else 60)
    print("-- 2. receive")
    if not quick:
        test_receive()
    print("-- 3. the chip as host: usb_host.asm (%d words), host logic, model keyboard" % len(assemble(src).words))
    for rate, seed in (((-0.015, 1),) if quick else ((-0.015, 1), (0.015, 2))):
        bad = full_chip(rate, seed, f"keyboard {rate * 100:+.1f} %", src, quiet=quick, reset_us=reset_us)
        for b in bad:
            print("FAIL:", b)
        fails.extend(bad)
    print("-- 4. USB mode off")
    test_off()
    return len(fails)


# ---- planted bugs
def patched(path, name, old, new):
    src = open(path, encoding="utf-8").read()
    assert src.count(old) >= 1, (name, old)
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(src.replace(old, new), path, "exec"), mod.__dict__)
    return mod


PLANTS = [
    ("transmit: stuffing after seven 1s", "engine",
     [("if self.usb_ones == 6:", "if self.usb_ones == 7:"), ('"usb_ones": (0, 6)', '"usb_ones": (0, 7)')]),
    ("transmit: NRZI inverted (a 1 changes the level)", "engine",
     [("        if b == 0:\n            self.usb_lvl ^= 1", "        if b == 1:\n            self.usb_lvl ^= 1")]),
    ("transmit: EOP SE0 one bit long", "engine", [("USB_EOP_J = 4 ", "USB_EOP_J = 2 ")]),
    ("transmit: SERFRAC carry ignored", "engine",
     [("return min(M16, self.cfg.serdiv + (s >> 8))", "return self.cfg.serdiv")]),
    ("listening empties the receive ring (as an arm does)", "engine",
     [("                    self._rx_reset(armed=True)\n                    self.usb_eop = False",
       "                    self._rx_reset(armed=True)\n                    self.usb_eop = False\n"
       "                    self._plant_clear = True"),
      ("        elif c.ser and arm and (rx0 or fdx0):",
       "        elif c.ser and (arm or getattr(self, '_plant_clear', False)) and (rx0 or fdx0):\n"
       "            self._plant_clear = False")]),
    ("receive: the wrong CRC16 residue (0x800D)", "engine", [("USB_CRC16_RESIDUE = 0xB001", "USB_CRC16_RESIDUE = 0x800D")]),
    ("receive: no unstuffing", "engine",
     [("if self.usb_rones == 6:", "if self.usb_rones == 7:"), ('"usb_rones": (0, 6)', '"usb_rones": (0, 7)')]),
    ("receive: sampled at the edge, not mid-bit", "engine", [("self.rx_gap = c.rxgap >> 1\n            return False\n        if self.rx_gap:",
                                                          "self.rx_gap = 0\n            return False\n        if self.rx_gap:")]),
    ("program: ACK sent for a NAK (status bit 10 ignored)", "asm", [("    jmp    !x, drop\n", "    mov    y, y\n")]),
    ("program: ACK 1.4 bit times early (one delay gone)", "asm", [("    mov    y, y        [31]", "    mov    y, y")]),
    ("host: the toggle check gone (a copy taken as a new report)", "host",
     [("        if (r.pid == U.PID_DATA1) != bool(self.ep1_toggle):\n            self.counts[\"dup\"] += 1\n"
       "            return None\n", "")]),
]


def plants():
    global E, H, QUIET, fails
    E0, H0 = E, H
    caught = 0
    for name, where, reps in PLANTS:
        src = SRC
        if where == "engine":
            mod = None
            text = open(os.path.join(HERE, "engine.py"), encoding="utf-8").read()
            for old, new in reps:
                assert text.count(old) == 1, (name, old)
                text = text.replace(old, new)
            spec = importlib.util.spec_from_loader("engine_planted", loader=None)
            mod = importlib.util.module_from_spec(spec)
            exec(compile(text, "engine.py", "exec"), mod.__dict__)
            E = mod
        elif where == "host":
            H = patched(os.path.join(HERE, "usb_host.py"), "usb_host_planted", reps[0][0], reps[0][1])
        else:
            for old, new in reps:
                assert src.count(old) == 1, (name, old)
                src = src.replace(old, new)
        fails, QUIET = [], True
        try:
            run(quick=True, src=src, reset_us=100)
            bad = len(fails)
        except Exception as ex:                       # a range check or an assertion stopping the model counts too
            bad = 1
            fails.append(f"{type(ex).__name__}: {ex}")
        print(f"  planted: {name:58s} {'caught' if bad else 'MISSED'}  ({(fails or [''])[0][:90]})")
        caught += bool(bad)
        E, H = E0, H0
    QUIET = False
    print("\n==== %s (%d of %d planted bugs caught) ====" % ("PASS" if caught == len(PLANTS) else "FAIL", caught,
                                                           len(PLANTS)))
    return caught == len(PLANTS)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "plant":
        sys.exit(0 if plants() else 1)
    bad = run()
    print("\n==== %s (%d problems) ====" % ("FAIL" if bad else "PASS", bad))
    sys.exit(1 if bad else 0)
