"""Host side of low-speed USB through the chip, in Python (the Pico's pico/usb_host.py will follow it): everything that
can wait (private/usb_ls.md, section 5.4). Tokens and their CRC5, data packets and their CRC16, DATA0/DATA1 toggles,
retries, enumeration, decoding boot reports.

It talks to a port with three calls, each standing for what the Pico does over SPI:
    port.transact(words) -> Reply or None   push one transaction's words in one burst (job words as below), wait for
                                            the engine program to finish it, read USBSTAT and the reply's words
    port.bus_reset()                        SE0 on the bus for 10 ms (a drive-low program), then usb_host.asm again
    port.idle(us)                           let time pass (the engine sends keep-alives)

Job words (programs/usb_host.asm): [7:0] the packet's bytes with SYNC, [14] a reply is expected (an ACK job follows:
0x0002 and 0xD280), [15] keep-alive. The chip ACKs a good DATA reply by itself; the host never sends an ACK.
"""
import usb_line as U

ACK_JOB = [0x0002, 0xD280]


def job(packet, reply=False):
    return [(len(packet) + 1) | (0x4000 if reply else 0)] + U.words_of(packet) + (ACK_JOB if reply else [])


class Reply:
    """The reply as the chip reports it: USBSTAT and the bytes from RXDATA (PID first)."""

    def __init__(self, stat, raw):
        self.stat, self.raw = stat, bytes(raw)
        self.pid = stat & 15
        self.pid_ok, self.crc_ok = bool(stat >> 4 & 1), bool(stat >> 5 & 1)
        self.stuff_err, self.bad = bool(stat >> 6 & 1), bool(stat >> 7 & 1)
        self.is_data = self.pid in (U.PID_DATA0, U.PID_DATA1)
        self.ok = self.pid_ok and not self.stuff_err and not self.bad and (self.crc_ok or not self.is_data)
        self.data = self.raw[1:-2] if self.is_data else b""

    def __repr__(self):
        return f"<{U.PID_NAMES.get(self.pid, self.pid)} {'ok' if self.ok else 'BAD'} {self.raw.hex(' ')}>"


class UsbError(Exception):
    pass


KEYS = {0x04 + i: chr(ord("a") + i) for i in range(26)}
KEYS.update({0x1E + i: str((i + 1) % 10) for i in range(10)})
KEYS.update({0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space"})
MODS = ["ctrl", "shift", "alt", "gui", "rctrl", "rshift", "ralt", "rgui"]


def report_text(r):
    """A boot report as a line: 'shift+a', or 'release' when nothing is held."""
    held = [MODS[i] for i in range(8) if r[0] >> i & 1] + [KEYS.get(k, f"key{k:02x}") for k in r[2:8] if k]
    return "+".join(held) if held else "release"


class UsbHost:
    def __init__(self, port, tries=40):
        self.port, self.tries = port, tries
        self.addr = 0
        self.ep1_toggle = 0
        self.errors = []
        self.counts = dict(transactions=0, timeouts=0, bad=0, naks=0, dup=0)

    def _x(self, words):
        self.counts["transactions"] += 1
        r = self.port.transact(words)
        if r is None:
            self.counts["timeouts"] += 1
        elif not r.ok:
            self.counts["bad"] += 1
        elif r.is_data:
            pid, errs = U.check_packet(r.raw)            # the host's own CRC check agrees with the chip's flag
            if errs:
                self.errors.append(f"chip said good, host finds {errs} in {r.raw.hex(' ')}")
        return r

    def _setup(self, req):
        for _ in range(self.tries):
            r = self._x(job(U.token(U.PID_SETUP, self.addr, 0)) + job(U.data(U.PID_DATA0, req), reply=True))
            if r is not None and r.ok and r.pid == U.PID_ACK:
                return
        raise UsbError(f"SETUP {req.hex(' ')} not ACKed")

    def _status_in(self):
        """A control transfer's IN status stage: a zero-length DATA1 (the chip ACKs it)."""
        for _ in range(self.tries):
            r = self._x(job(U.token(U.PID_IN, self.addr, 0), reply=True))
            if r is None or not r.ok or r.pid == U.PID_NAK:
                continue
            if r.pid == U.PID_STALL:
                raise UsbError("STALL in the status stage")
            if r.pid == U.PID_DATA1 and not r.data:
                return
            self.errors.append(f"status stage answered {r!r}")
        raise UsbError("no status stage")

    def _status_out(self):
        for _ in range(self.tries):
            r = self._x(job(U.token(U.PID_OUT, self.addr, 0)) + job(U.data(U.PID_DATA1, b""), reply=True))
            if r is not None and r.ok and r.pid == U.PID_ACK:
                return
            if r is not None and r.ok and r.pid == U.PID_STALL:
                raise UsbError("STALL in the status stage")
        raise UsbError("no status stage")

    def control_in(self, req):
        """SETUP, IN data stage (DATA1, DATA0, ... until wLength or a short packet), OUT status. Returns the data."""
        self._setup(req)
        wlength = req[6] | req[7] << 8
        out, toggle, tries = b"", 1, 0
        while len(out) < wlength:
            tries += 1
            if tries > 4 * self.tries:
                raise UsbError("data stage did not finish")
            r = self._x(job(U.token(U.PID_IN, self.addr, 0), reply=True))
            if r is None or not r.ok:
                continue
            if r.pid == U.PID_NAK:
                continue
            if r.pid == U.PID_STALL:
                raise UsbError(f"STALL for {req.hex(' ')}")
            if not r.is_data:
                self.errors.append(f"data stage answered {r!r}")
                continue
            if (r.pid == U.PID_DATA1) != bool(toggle):    # our ACK was lost: the chip ACKed the copy, drop it
                self.counts["dup"] += 1
                continue
            out += r.data
            toggle ^= 1
            if len(r.data) < 8:
                break
        self._status_out()
        return out

    def control_nodata(self, req):
        self._setup(req)
        self._status_in()

    def control_out(self, req, payload):
        self._setup(req)
        for _ in range(self.tries):
            r = self._x(job(U.token(U.PID_OUT, self.addr, 0)) + job(U.data(U.PID_DATA1, payload), reply=True))
            if r is not None and r.ok and r.pid == U.PID_ACK:
                break
            if r is not None and r.ok and r.pid == U.PID_STALL:
                raise UsbError("STALL in the data stage")
        else:
            raise UsbError("OUT data not ACKed")
        self._status_in()

    # ---- standard requests
    @staticmethod
    def req(bm, request, value=0, index=0, length=0):
        return bytes([bm, request, value & 0xFF, value >> 8, index & 0xFF, index >> 8, length & 0xFF, length >> 8])

    def get_descriptor(self, kind, index=0, length=255, lang=0, bm=0x80):
        return self.control_in(self.req(bm, 6, kind << 8 | index, lang, length))

    def enumerate(self, addr=1):
        """Bus reset, the device descriptor's first 8 bytes, SET_ADDRESS, the descriptors, SET_CONFIGURATION, boot
        protocol, no idle repeat. Returns a dict of what was read."""
        self.port.bus_reset()
        self.addr = 0
        info = {}
        info["dev8"] = self.get_descriptor(1, length=8)
        self.control_nodata(self.req(0x00, 5, addr))
        self.addr = addr
        info["device"] = d = self.get_descriptor(1, length=18)
        info["vid"], info["pid"] = d[8] | d[9] << 8, d[10] | d[11] << 8
        c9 = self.get_descriptor(2, length=9)
        info["config"] = c = self.get_descriptor(2, length=c9[2] | c9[3] << 8)
        lang = self.get_descriptor(3, 0)
        langid = lang[2] | lang[3] << 8
        for key, idx in (("manufacturer", d[14]), ("product", d[15])):
            s = self.get_descriptor(3, idx, lang=langid) if idx else b"\x02\x03"
            info[key] = s[2:].decode("utf-16-le")
        rlen = next((c[i + 7] | c[i + 8] << 8 for i in range(len(c) - 8) if c[i] == 9 and c[i + 1] == 0x21), None)
        if rlen is None:
            raise UsbError(f"no HID descriptor in the configuration {c.hex(' ')}")
        info["report_desc"] = self.get_descriptor(0x22, 0, length=rlen, bm=0x81)
        self.control_nodata(self.req(0x00, 9, c[5]))                 # SET_CONFIGURATION
        self.control_nodata(self.req(0x21, 0x0B, 0, 0))              # SET_PROTOCOL boot
        self.control_nodata(self.req(0x21, 0x0A, 0, 0))              # SET_IDLE 0
        self.ep1_toggle = 0
        return info

    def set_leds(self, bits):
        self.control_out(self.req(0x21, 9, 0x0200, 0, 1), bytes([bits]))

    def poll(self):
        """One interrupt IN poll of endpoint 1: a new report, or None (NAK, a copy, a bad reply, no reply)."""
        r = self._x(job(U.token(U.PID_IN, self.addr, 1), reply=True))
        if r is None or not r.ok:
            return None
        if r.pid == U.PID_NAK:
            self.counts["naks"] += 1
            return None
        if not r.is_data:
            self.errors.append(f"endpoint 1 answered {r!r}")
            return None
        if (r.pid == U.PID_DATA1) != bool(self.ep1_toggle):
            self.counts["dup"] += 1
            return None
        self.ep1_toggle ^= 1
        return r.data
