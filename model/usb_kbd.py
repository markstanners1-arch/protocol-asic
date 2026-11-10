"""Model low-speed USB keyboard (HID boot protocol) on the two wires, clocked every system clock (like model/ds18b20.py).

    kbd = UsbKeyboard(clk_hz, rate=+0.01, seed=1, script=[...])
    each clock:  d = kbd.drive()            # (D+, D-) while the keyboard drives the pair, else None
                 kbd.clock(dp, dm, host)    # the pair as it is this clock; host = the host drives it

The keyboard pulls D- up (the bus is J when nobody drives it). It reads the host's packets with its own clock: every
run of one line state between changes is counted in its own bit times (rate off nominal by `rate`, e.g. +-0.015), as a
real device's receiver does, then NRZI-decoded and unstuffed by model/usb_line.py. It answers 2 to 7 of its bit times
after the host's EOP, with D- changing `skew` clocks after D+ (short SE0 or SE1 at each crossing).

It holds device, configuration, HID report and string descriptors; answers GET_DESCRIPTOR, SET_ADDRESS (in force after
the status stage), SET_CONFIGURATION, SET_PROTOCOL, SET_IDLE and SET_REPORT (the LED byte); STALLs anything else; and
has an interrupt IN endpoint 1 fed with boot reports from a script. It NAKs some polls, can send some reports with a
bad CRC (`corrupt`: the host must not ACK them; they are sent again) and can miss some of the host's ACKs (`deaf`: the
report is sent again with the same toggle; the host must ACK it and throw the copy away).

Everything it checks on the host goes in .errors:
  - the host's bit rate (within 0.1 % of 1.5 Mbit/s) and every edge within 1.5 clocks of where the rate puts it
  - stuffing, SYNC, the PID check, CRC5 on tokens, CRC16 on data, whole bytes
  - the EOP: SE0 for 1.875 to 2.25 bit times *(spec, check: low-speed source EOP 1.25 to 1.5 us)*, then J driven by
    the host for 0.75 to 1.25 bit times before it lets go
  - at least 2 bit times between any EOP and the host's next packet; the host's ACK 2 to 7.5 bit times after our EOP;
    the DATA after a SETUP or OUT token within 18 bit times
  - a keep-alive or packet at least every 3 ms once reset (else it would suspend)
  - DATA0 after SETUP, DATA1 in a status stage, no contention (the bench reports that)
  - a good DATA we sent is ACKed; a bad one is not
"""
import bisect
import random
import usb_line as U
from usb_line import J, K, SE0, SE1

LS_RATE = 1_500_000


def boot_report(mods=0, keys=()):
    keys = list(keys)[:6]
    return bytes([mods, 0] + keys + [0] * (6 - len(keys)))


def string_desc(s):
    b = s.encode("utf-16-le")
    return bytes([2 + len(b), 3]) + b


VID, PID = 0x1209, 0x7101               # the model's own numbers
DEVICE_DESC = bytes([18, 1, 0x10, 0x01, 0, 0, 0, 8, VID & 0xFF, VID >> 8, PID & 0xFF, PID >> 8, 0x00, 0x01, 1, 2, 0, 1])
REPORT_DESC = bytes.fromhex(            # the HID 1.11 appendix B boot keyboard report descriptor
    "05010906a101050719e029e71500250175019508810295017508810195057501050819012905910295017503910195067508150025650507"
    "190029658100c0")
CONFIG_DESC = (bytes([9, 2, 34, 0, 1, 1, 0, 0xA0, 50])            # 1 interface, remote wakeup, 100 mA
               + bytes([9, 4, 0, 0, 1, 3, 1, 1, 0])                # HID, boot, keyboard
               + bytes([9, 0x21, 0x10, 0x01, 0, 1, 0x22, len(REPORT_DESC), 0])
               + bytes([7, 5, 0x81, 3, 8, 0, 10]))                 # EP1 IN, interrupt, 8 bytes, 10 ms
STRINGS = {0: bytes([4, 3, 0x09, 0x04]), 1: string_desc("ProtocolASIC"), 2: string_desc("Model keyboard")}


class Tx:
    """A packet on the wire from a sender with bit time p (clocks), starting at ts (clock, fractional), D- `skew`
    clocks behind D+, every symbol boundary moved by up to +-jitter clocks (rnd). levels(t) gives (D+, D-) at clock t,
    or None outside the packet."""

    def __init__(self, symbols, ts, p, skew=0.0, jitter=0.0, rnd=None):
        self.syms, self.ts, self.p, self.skew = list(symbols), ts, p, skew
        n = len(self.syms)
        self.bounds = [ts + i * p + ((rnd.uniform(-jitter, jitter) if jitter and 0 < i < n else 0.0))
                       for i in range(n + 1)]
        self.end = self.bounds[-1] + max(0.0, skew)
        self.eop_j = self.bounds[n - 1]                     # the SE0-to-J change

    def _sym(self, x):
        if x < self.bounds[0]:
            return J
        i = bisect.bisect_right(self.bounds, x) - 1
        return self.syms[min(i, len(self.syms) - 1)]

    def levels(self, t):
        if t < self.ts + min(0.0, self.skew) or t >= self.end:
            return None
        return U.LEVELS[self._sym(t)][0], U.LEVELS[self._sym(t - self.skew)][1]


class UsbKeyboard:
    def __init__(self, clk_hz, rate=0.0, seed=1, script=(), skew=0.0, naks=(0, 2), corrupt=0, deaf=0,
                 debounce=3):
        self.clk_hz = clk_hz
        self.pn = clk_hz / LS_RATE                  # the nominal bit time, clocks
        self.pd = self.pn * (1 + rate)              # the keyboard's own bit time
        self.rnd = random.Random(seed)
        self.skew, self.naks, self.corrupt, self.deaf, self.debounce = skew, naks, corrupt, deaf, debounce
        self.reports = [bytes(r) for r in script]   # boot reports still to send, in order
        self.sent_reports = []                       # reports the host ACKed (as far as the keyboard knows)
        self.t = 0
        self.errors, self.log = [], []
        self.counts = dict(packets=0, keepalives=0, resets=0, naks=0, data=0, acked=0, corrupt=0, deaf=0, stalls=0,
                           no_ack=0)
        self.cur, self.cur_t, self.raw, self.raw_t = J, 0, J, 0
        self.pkt = None                 # segments of the host packet coming in, (state, clocks)
        self.pkt_t = self.se0_t = None
        self.last_eop = -1e9            # the last SE0-to-J change on the bus (anyone's)
        self.release = None             # the host's EOP J began here: watching for it to let go
        self.last_activity = None       # None until the first bus reset
        self.tx = None                  # our packet on the wire
        self.awaiting = None            # ("data", pid, ep, deadline) after a SETUP / OUT, ("hs", good, kind, deadline)
        self.leds = None
        self.ack_windows = []           # the host's ACKs: bit times from our EOP's SE0-to-J to their SYNC
        self.last_eop_dev = -1e9
        self.tx_info = None
        self.attached = True
        self._reset_state()

    # ---- state
    def _reset_state(self):
        self.addr, self.new_addr, self.config = 0, None, 0
        self.ctl = None                 # the control transfer in progress
        self.ep1_toggle = 0
        self.nak_left = None
        self.rep_sends, self.rep_deaf = 0, False

    def err(self, msg):
        self.errors.append(f"{self.t / self.clk_hz * 1e6:.1f} us: {msg}")

    # ---- the wires
    def drive(self):
        return self.tx.levels(self.t) if self.tx is not None else None

    def clock(self, dp, dm, host=False):
        t = self.t
        self.t += 1
        if self.tx is not None:
            if t >= self.tx.end:
                self._sent()
            else:
                return
        s = U.sym_of(dp, dm)
        if s != self.raw:
            self.raw, self.raw_t = s, t
        if self.raw != self.cur and t - self.raw_t + 1 >= self.debounce:
            self._change(self.raw, self.raw_t)
        if self.release is not None and not host:
            j = (t - self.release) / self.pn
            if not 0.75 <= j <= 1.25:
                self.err(f"host drove J for {j:.2f} bit times after its SE0")
            self.release = None
        if self.awaiting and self.pkt is None and t > self.awaiting[-1]:
            self._timeout()
        if self.last_activity is not None and t - self.last_activity > 3e-3 * self.clk_hz:
            self.err("no keep-alive for 3 ms: suspended")
            self.last_activity = t

    def _change(self, new, at):
        old, dur = self.cur, at - self.cur_t
        self.cur, self.cur_t = new, at
        if self.last_activity is not None:
            self.last_activity = at
        if new == SE1 or old == SE1:
            self.err("SE1 on the bus")
        if self.pkt is None:
            if old == J and new == K:                       # a packet starts
                self.pkt, self.pkt_t = [], at
                gap = (at - self.last_eop) / self.pn
                if gap < 2:
                    self.err(f"host packet {gap:.2f} bit times after the last EOP")
            elif old == J and new == SE0:
                self.se0_t = at
            elif old == SE0 and new == J and self.se0_t is not None:
                self._lone_se0(self.se0_t, at)
            return
        if old in (J, K):
            self.pkt.append((old, dur))
        if new == SE0:
            self.se0_t = at
        elif old == SE0 and new == J:
            segs, t0, t1 = self.pkt, self.pkt_t, self.se0_t
            self.pkt = None
            self._host_packet(segs, t0, t1, at)
        elif old == SE0:
            self.err("SE0 followed by K")
            self.pkt = None

    def _lone_se0(self, t0, t1):
        d = (t1 - t0) / self.pn
        self.last_eop = t1
        if t1 - t0 >= 2.5e-6 * self.clk_hz:
            self.counts["resets"] += 1
            self.log.append("bus reset")
            self._reset_state()
            self.awaiting = None
            self.last_activity = t1
            return
        if not 1.875 <= d <= 2.25:
            self.err(f"keep-alive SE0 of {d:.2f} bit times")
        self.counts["keepalives"] += 1
        self.release = t1

    # ---- a host packet, from its runs of J and K
    def _host_packet(self, segs, t0, t_se0, t_j):
        self.last_eop, self.release = t_j, t_j
        n = [max(1, round(d / self.pd)) for _, d in segs]
        syms = [s for (s, _), k in zip(segs, n) for _ in range(k)]
        pkt, errs = U.decode(syms + U.EOP)
        total = sum(n)
        period = (t_se0 - t0) / total
        if abs(period / self.pn - 1) > 1e-3:
            errs.append(f"bit rate {LS_RATE * self.pn / period:.0f} bit/s")
        worst, pos, acc = 0.0, 0, 0
        for (s, d), k in zip(segs, n):           # every edge where the nominal rate puts it
            pos += k
            acc += d
            worst = max(worst, abs(acc - pos * self.pn))
        if worst > 1.5:
            errs.append(f"an edge {worst:.2f} clocks from its place")
        se0 = (t_j - t_se0) / self.pn
        if not 1.875 <= se0 <= 2.25:
            errs.append(f"EOP SE0 of {se0:.2f} bit times")
        self.counts["packets"] += 1
        if errs:
            self.err("host packet " + pkt.hex(" ") + ": " + "; ".join(errs))
            return
        pid, perrs = U.check_packet(pkt)
        if perrs:
            self.err("host packet " + pkt.hex(" ") + ": " + "; ".join(perrs))
            return
        self._packet(pid, pkt, t0, t_j)

    # ---- the protocol
    def _send(self, pkt, after, good=True, kind=None):
        ts = after + self.rnd.uniform(2.2, 7.0) * self.pd
        self.tx = Tx(U.encode(pkt), ts, self.pd, self.skew)
        self.tx_info = (pkt, good, kind)

    def _sent(self):
        pkt, good, kind = self.tx_info
        self.last_eop = self.last_eop_dev = self.tx.eop_j
        self.cur, self.cur_t, self.raw, self.raw_t = J, self.t, J, self.t
        if pkt[0] & 15 in (U.PID_DATA0, U.PID_DATA1):
            self.awaiting = ("hs", good, kind, self.tx.eop_j + 18 * self.pn)
        self.tx = None

    def _timeout(self):
        a = self.awaiting
        self.awaiting = None
        if a[0] == "data":
            self.err(f"no DATA within 18 bit times of the {U.PID_NAMES[a[1]]} token")
        else:
            self.counts["no_ack"] += 1
            if a[1]:
                self.err("a good DATA was not ACKed")

    def _packet(self, pid, pkt, t0, t_j):
        a, self.awaiting = self.awaiting, None
        if a and a[0] == "hs":
            if pid != U.PID_ACK:
                self.counts["no_ack"] += 1
                if a[1]:
                    self.err(f"a good DATA answered with {U.PID_NAMES.get(pid, pid)}, not ACK")
            else:
                w = (t0 - self.last_eop_dev) / self.pn
                self.ack_windows.append(w)
                if not 2 <= w <= 7.5:
                    self.err(f"ACK {w:.2f} bit times after our EOP")
                if not a[1]:
                    self.err("a bad DATA was ACKed")
                elif a[2] == "report" and self.deaf and len(self.sent_reports) % self.deaf == self.deaf - 1 \
                        and not self.rep_deaf:
                    self.counts["deaf"] += 1               # we miss this ACK: the report goes again, same toggle
                    self.rep_deaf = True
                else:
                    self._acked(a[2])
                return
        if pid in (U.PID_SETUP, U.PID_OUT, U.PID_IN):
            addr, ep = pkt[1] & 0x7F, (pkt[1] >> 7 | pkt[2] << 1) & 15
            if addr != self.addr:
                return
            if pid == U.PID_IN:
                self._in(ep, t_j)
            else:
                self.awaiting = ("data", pid, ep, t_j + 18 * self.pn)
            return
        if pid in (U.PID_DATA0, U.PID_DATA1):
            if not a or a[0] != "data":
                self.err("DATA without a token")
                return
            self._data(a[1], a[2], pid, pkt[1:-2], t_j)
            return
        self.err(f"unexpected {U.PID_NAMES.get(pid, pid)} from the host")

    def _hs(self, pid, after):
        self._send(U.handshake(pid), after)

    def _data_out(self, pid, payload, after, kind):
        pkt = U.data(pid, payload)
        good = True
        if kind == "report":
            if self.corrupt and len(self.sent_reports) % self.corrupt == self.corrupt - 1 and self.rep_sends == 0:
                pkt = bytearray(pkt); pkt[1] ^= 0x10; pkt = bytes(pkt)     # one bit of the report: CRC16 now wrong
                good = False
                self.counts["corrupt"] += 1
            self.rep_sends += 1
        self.counts["data"] += 1
        self._send(pkt, after, good, kind)

    def _in(self, ep, after):
        if ep == 0:
            c = self.ctl
            if c is None or c["stage"] == "stall":
                self.counts["stalls"] += 1
                self._hs(U.PID_STALL, after)
            elif c["stage"] == "in":
                chunk = c["data"][c["pos"]:c["pos"] + 8]
                c["chunk"] = len(chunk)
                self._data_out(U.PID_DATA1 if c["toggle"] else U.PID_DATA0, chunk, after, "ctl")
            elif c["stage"] == "status_in":
                self._data_out(U.PID_DATA1, b"", after, "status")
            else:
                self.err(f"IN in control stage {c['stage']}")
                self._hs(U.PID_STALL, after)
        elif ep == 1:
            if not self.config or not self.reports:
                self.counts["naks"] += 1
                self._hs(U.PID_NAK, after)
                return
            if self.nak_left is None:
                self.nak_left = self.rnd.randint(*self.naks)
            if self.nak_left > 0:
                self.nak_left -= 1
                self.counts["naks"] += 1
                self._hs(U.PID_NAK, after)
                return
            self._data_out(U.PID_DATA1 if self.ep1_toggle else U.PID_DATA0, self.reports[0], after, "report")
        else:
            self._hs(U.PID_STALL, after)

    def _acked(self, kind):
        self.counts["acked"] += 1
        if kind == "report":
            self.sent_reports.append(self.reports.pop(0))
            self.ep1_toggle ^= 1
            self.nak_left = None
            self.rep_sends, self.rep_deaf = 0, False
        elif kind == "ctl":
            c = self.ctl
            c["pos"] += c["chunk"]
            c["toggle"] ^= 1
            if c["chunk"] < 8 or c["pos"] >= c["len"]:
                c["stage"] = "status_out"
        elif kind == "status":
            c, self.ctl = self.ctl, None
            if c and c.get("addr") is not None:
                self.addr = c["addr"]
                self.log.append(f"address {self.addr}")
            if c and c.get("config") is not None:
                self.config, self.ep1_toggle = c["config"], 0
                self.log.append(f"configuration {self.config}")

    def _data(self, tok, ep, pid, payload, after):
        if tok == U.PID_SETUP:
            if ep != 0 or len(payload) != 8:
                self.err("SETUP not to endpoint 0 with 8 bytes")
                return
            if pid != U.PID_DATA0:
                self.err("SETUP's data is not DATA0")
            self._hs(U.PID_ACK, after)
            self._setup(payload)
            return
        c = self.ctl
        if ep != 0 or c is None:
            self.err("OUT data with no control transfer")
            self._hs(U.PID_STALL, after)
            return
        if c["stage"] == "out":
            if pid != U.PID_DATA1:
                self.err("SET_REPORT data is not DATA1")
            self.leds = payload[0] if payload else None
            self.log.append(f"LEDs {self.leds:#04x}")
            c["stage"] = "status_in"
            self._hs(U.PID_ACK, after)
        elif c["stage"] in ("in", "status_out"):
            if pid != U.PID_DATA1 or payload:
                self.err("status stage OUT is not a zero-length DATA1")
            self.ctl = None
            self._hs(U.PID_ACK, after)
        else:
            self.err(f"OUT in control stage {c['stage']}")
            self._hs(U.PID_STALL, after)

    def _setup(self, s):
        bm, req, wv, wi, wl = s[0], s[1], s[2] | s[3] << 8, s[4] | s[5] << 8, s[6] | s[7] << 8
        self.log.append(f"SETUP {s.hex(' ')}")
        c = {"stage": "status_in"}
        if bm == 0x80 and req == 6:
            d = {1: DEVICE_DESC, 2: CONFIG_DESC}.get(wv >> 8)
            if wv >> 8 == 3:
                d = STRINGS.get(wv & 0xFF)
            c = {"stage": "stall"} if d is None else {"stage": "in", "data": d[:wl], "len": min(wl, len(d)),
                                                       "pos": 0, "toggle": 1}
        elif bm == 0x81 and req == 6 and wv >> 8 == 0x22:
            c = {"stage": "in", "data": REPORT_DESC[:wl], "len": min(wl, len(REPORT_DESC)), "pos": 0, "toggle": 1}
        elif bm == 0x00 and req == 5:
            c["addr"] = wv & 0x7F
        elif bm == 0x00 and req == 9:
            c["config"] = wv & 0xFF
        elif bm == 0x21 and req in (0x0A, 0x0B):
            pass
        elif bm == 0x21 and req == 9 and wl == 1:
            c = {"stage": "out"}
        else:
            c = {"stage": "stall"}
        if c["stage"] == "in" and c["len"] % 8 == 0 and c["len"] < wl:
            pass                                # a zero-length packet ends it (not met by these descriptors)
        self.ctl = c
