"""The model keyboard (model/usb_kbd.py) and the host logic (model/usb_host.py), with an ideal host port in Python
(no chip): the reference for model/test_usb.py, and a check that the keyboard catches a host that breaks the rules.

1. Enumeration and keys, at the keyboard's rate -1.5 % and +1.5 %, D- 1.5 clocks behind D+, edges moved +-1 clock:
   the descriptors read back equal the model's; SET_ADDRESS, SET_CONFIGURATION, boot protocol; the LEDs set in a
   scripted order; the scripted keys read back line by line, with NAKs, reports sent with a bad CRC (not ACKed, sent
   again) and ACKs the keyboard misses (the copy ACKed and dropped by the host's toggle check); no keyboard errors.
2. Host faults, each of which the keyboard must log: bit rate 1 % off, an EOP with one bit of SE0, edges +-3 clocks
   off, an ACK 1.5 or 9 bit times after the data, 1 bit between packets, a SETUP's DATA0 25 bit times late, no ACK
   for good data, an ACK for bad data, no keep-alive for 4 ms, a token with a bad CRC5, a SETUP with DATA1, a status
   stage with DATA0.
Run:  python model/test_usb_kbd.py
"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_line as U
from usb_kbd import UsbKeyboard, Tx, runs_decode, boot_report, DEVICE_DESC, CONFIG_DESC, REPORT_DESC, VID, PID
from usb_host import UsbHost, UsbError, Reply, job, report_text

CLK = 40_000_000
# (expected line, modifiers, key codes): HID usage codes written out, not taken from usb_host's table
SCRIPT = [("a", 0, [0x04]), ("s", 0, [0x16]), ("1", 0, [0x1E]), ("2", 0, [0x1F]), ("shift+a", 0x02, [0x04]),
          ("Enter", 0, [0x28]), ("h", 0, [0x0B]), ("i", 0, [0x0C]), ("ctrl+alt+Backspace", 0x05, [0x2A])]
LEDS = [0x01, 0x02, 0x04, 0x07, 0x00]           # Num, Caps, Scroll, all, none


def script_reports():
    out, lines = [], []
    for line, mods, keys in SCRIPT:
        out += [boot_report(mods, keys), boot_report()]
        lines += [line, "release"]
    return out, lines


class RefPort:
    """An ideal host port: the job words played straight onto the wire by Python, with chosen faults."""

    def __init__(self, kbd, rate=0.0, se0_bits=2, ack_bits=3.0, gap_bits=3.0, data_gap_bits=None, ack="good",
                 jitter=0.0, keepalive=True, reset_us=200, seed=1):
        self.kbd, self.pn = kbd, CLK / 1.5e6
        self.p = self.pn * (1 + rate)
        self.se0_bits, self.ack_bits, self.gap_bits, self.data_gap_bits = se0_bits, ack_bits, gap_bits, data_gap_bits
        self.ack, self.jitter, self.keepalive, self.reset_us = ack, jitter, keepalive, reset_us
        self.rnd = random.Random(seed)
        self.t, self.last_eop, self.last_ka = 0, -1e9, 0
        self.errors = []

    def clock(self, host=None):
        kd = self.kbd.drive()
        if host is not None and kd is not None:
            self.errors.append(f"contention at {self.t}")
        bus = host if host is not None else (kd if kd is not None else (0, 1))
        self.kbd.clock(*bus, host=host is not None)
        self.t += 1

    def _send(self, syms, gap):
        start = int(self.last_eop + gap * self.pn) + 1
        while self.t < start:
            self.clock()
        if self.se0_bits != 2:
            syms = syms[:-3] + [U.SE0] * self.se0_bits + [U.J]
        tx = Tx(syms, self.t, self.p, jitter=self.jitter, rnd=self.rnd)
        while self.t < tx.end:
            self.clock(tx.levels(self.t) or (0, 1))
        self.last_eop = self.last_ka = tx.eop_j

    def _receive(self):
        deadline = self.last_eop + 18 * self.pn
        while self.kbd.drive() is None and self.t < deadline:
            self.clock()
        if self.kbd.drive() is None:
            return None
        t0, samples = self.t, [(0, 1)]
        while self.kbd.drive() is not None:
            samples.append(self.kbd.drive())
            self.clock()
        pkt, errs, eop = runs_decode(samples, self.pn)
        self.last_eop = t0 - 1 + (eop if eop is not None else len(samples))
        pid, perrs = U.check_packet(pkt)
        is_data = pid in (U.PID_DATA0, U.PID_DATA1)
        stat = ((pid or 0) & 15 | int("PID check" not in perrs and bool(pkt)) << 4
                | int(is_data and not perrs) << 5 | int(any("stuff" in e for e in errs)) << 6
                | int(any("stuff" not in e for e in errs)) << 7 | min(15, len(pkt)) << 10)
        return Reply(stat, pkt)

    def transact(self, words):
        i, reply, prev_reply = 0, None, True
        while i < len(words):
            jw = words[i]
            i += 1
            if jw & 0x8000:
                self._send(U.keepalive(), self.gap_bits)
                continue
            n = jw & 0xFF
            nw = (n + 1) // 2
            b = b"".join(w.to_bytes(2, "little") for w in words[i:i + nw])[:n]
            i += nw
            gap = self.gap_bits if (prev_reply or self.data_gap_bits is None) else self.data_gap_bits
            self._send(U.encode(b[1:]), gap)
            prev_reply = bool(jw & 0x4000)
            if jw & 0x4000:
                i += 2                                     # the ACK job and its word
                reply = self._receive()
                if reply is not None and reply.is_data and (self.ack == "all" or (self.ack == "good" and reply.ok)):
                    self._send(U.encode(U.handshake(U.PID_ACK)), self.ack_bits)
        return reply

    def bus_reset(self):
        for _ in range(int(self.reset_us * 1e-6 * CLK)):
            self.clock((0, 0))
        self.last_eop = self.t
        self.idle(50)

    def idle(self, us):
        end = self.t + us * 1e-6 * CLK
        while self.t < end:
            if self.keepalive and self.t - self.last_ka > 1e-3 * CLK:
                self._send(U.keepalive(), 3)
            else:
                self.clock()


fails = []


def check(what, got, want):
    ok = got == want
    print(f"{'ok:  ' if ok else 'FAIL:'} {what} = {got!r}" + ("" if ok else f", expected {want!r}"))
    if not ok:
        fails.append(what)
    return ok


def read_keys(host, n, limit=2000):
    lines = []
    for _ in range(limit):
        r = host.poll()
        if r is not None:
            lines.append(report_text(r))
            if len(lines) == n:
                break
    return lines


def full_run(port_of, rate, seed, label, quiet=False):
    """Enumerate, set the LEDs, read the scripted keys. port_of(kbd) makes the port. Returns the problems."""
    reports, want = script_reports()
    kbd = UsbKeyboard(CLK, rate=rate, seed=seed, script=reports, skew=1.5, jitter=1.0, naks=(0, 2), corrupt=3,
                      deaf=4)
    port = port_of(kbd)
    host = UsbHost(port)
    bad = []

    def chk(what, got, want_):
        if got != want_:
            bad.append(f"{label}: {what} = {got!r}, expected {want_!r}")
        elif not quiet:
            print(f"ok:   {label}: {what}")
    try:
        info = host.enumerate()
        chk("device descriptor", info["device"], DEVICE_DESC)
        chk("first 8 bytes", info["dev8"], DEVICE_DESC[:8])
        chk("VID:PID", (info["vid"], info["pid"]), (VID, PID))
        chk("configuration descriptor", info["config"], CONFIG_DESC)
        chk("strings", (info["manufacturer"], info["product"]), ("ProtocolASIC", "Model keyboard"))
        chk("report descriptor", info["report_desc"], REPORT_DESC)
        chk("address and configuration", (kbd.addr, kbd.config), (1, 1))
        for v in LEDS:
            host.set_leds(v)
        chk("LEDs in order", [l for l in kbd.log if l.startswith("LEDs")], [f"LEDs {v:#04x}" for v in LEDS])
        lines = read_keys(host, len(want))
        chk("keys read back line by line", lines, want)
        if not quiet:
            for got, w in zip(lines, want):
                print(f"        {w:20s} -> {got}")
        port.idle(3500)                                       # nothing to send: keep-alives keep it awake
    except UsbError as e:
        bad.append(f"{label}: {e}")
    chk("keyboard errors", kbd.errors[:3], [])
    chk("host errors", host.errors[:3], [])
    chk("port errors", getattr(port, "errors", [])[:3], [])
    c = kbd.counts
    chk("NAKs, bad reports, missed ACKs and dropped copies all exercised",
        (c["naks"] > 0, c["corrupt"] > 0, c["deaf"] > 0, host.counts["dup"] >= c["deaf"]), (True,) * 4)
    if not quiet:
        w = kbd.ack_windows
        print(f"        {len(w)} ACKs, {min(w):.2f} to {max(w):.2f} bit times after the keyboard's EOP; "
              f"counts {c}; host {host.counts}")
    return bad, kbd, host


def fault(name, want, port_kw=None, kbd_kw=None, action="get8"):
    kbd = UsbKeyboard(CLK, seed=3, script=[boot_report(0, [4]), boot_report()], **(kbd_kw or {}))
    port = RefPort(kbd, **(port_kw or {}))
    host = UsbHost(port, tries=3)
    try:
        if action == "get8":
            port.bus_reset()
            host.get_descriptor(1, length=8)
        elif action == "poll":
            host.enumerate()
            read_keys(host, 2, limit=20)
        elif action == "idle":
            port.bus_reset()
            port.keepalive = False
            port.idle(4000)
        else:
            port.bus_reset()
            port.transact(action)
            port.idle(100)
    except UsbError:
        pass
    hit = [e for e in kbd.errors if want in e]
    ok = bool(hit)
    print(f"{'ok:  ' if ok else 'FAIL:'} {name}: {hit[0] if hit else kbd.errors[:2]}")
    if not ok:
        fails.append(name)


def run():
    print("-- 1. enumeration and keys through an ideal host port")
    for rate, seed in ((-0.015, 1), (0.015, 2)):
        bad, _, _ = full_run(lambda k: RefPort(k), rate, seed, f"keyboard {rate * 100:+.1f} %")
        for b in bad:
            print("FAIL:", b)
        fails.extend(bad)
    print("-- 2. host faults the keyboard must catch")
    tok = bytearray(U.token(U.PID_SETUP, 0, 0)); tok[2] ^= 0x80
    fault("bit rate 1 % fast", "bit rate", {"rate": -0.01})
    fault("EOP with 1 bit of SE0", "EOP SE0 of", {"se0_bits": 1})
    fault("edges +-3 clocks", "an edge", {"jitter": 3.0})
    fault("ACK 1.5 bit times after the data", "ACK 1.5", {"ack_bits": 1.5})
    fault("ACK 9 bit times after the data", "ACK 9.", {"ack_bits": 9})
    fault("1 bit between SETUP and its DATA0", "after the last EOP", {"gap_bits": 1.0})
    fault("SETUP's DATA0 25 bit times late", "no DATA within 18", {"data_gap_bits": 25})
    fault("no ACK for good data", "a good DATA", {"ack": "never"})
    fault("an ACK for bad data", "a bad DATA was ACKed", {"ack": "all"}, {"corrupt": 1}, action="poll")
    fault("no keep-alive for 4 ms", "suspended", action="idle")
    fault("a token with a bad CRC5", "CRC5", action=job(bytes(tok)))
    fault("SETUP with DATA1", "not DATA0", action=job(U.token(U.PID_SETUP, 0, 0))
          + job(U.data(U.PID_DATA1, UsbHost.req(0x80, 6, 0x100, 0, 8)), reply=True))
    fault("status stage with DATA0", "status stage OUT", action=job(U.token(U.PID_SETUP, 0, 0))
          + job(U.data(U.PID_DATA0, UsbHost.req(0x80, 6, 0x100, 0, 8)), reply=True) + job(U.token(U.PID_IN, 0, 0), True)
          + job(U.token(U.PID_OUT, 0, 0)) + job(U.data(U.PID_DATA0, b""), reply=True))
    return len(fails)


if __name__ == "__main__":
    bad = run()
    print("\n==== %s (%d problems) ====" % ("FAIL" if bad else "PASS", bad))
    sys.exit(1 if bad else 0)
