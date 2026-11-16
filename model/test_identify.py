"""Blind identification, end to end without hardware: simulated targets drive the real engine programs
(programs/measure_pulse.asm for low pulses, measure_high.asm for high pulses) in the Python model, and pico/identify_core.py
classifies what they measured. Each target must come out as what it is, and the I2C pair must be found as a pair.
    python model/test_identify.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "pico"))
from asm import assemble
from engine import Engine, Config
import identify_core as ic

LOW = assemble(open(os.path.join(ROOT, "programs", "measure_pulse.asm")).read())
HIGH = assemble(open(os.path.join(ROOT, "programs", "measure_high.asm")).read())


def expand(segs, tick):
    """[(level, microseconds), ...] -> one level per tick."""
    out, carry = [], 0.0
    for lvl, us in segs:
        n = us / tick + carry
        k = int(n)
        carry = n - k
        out += [lvl] * k
    return out


def measure(levels, pin, tick):
    """Run both programs on one pin (bit `pin` of each sample) at one model clock per tick; widths in us."""
    res = []
    for prog in (LOW, HIGH):
        eng = Engine(prog, Config.for_program(prog, in_base=pin))
        got = []
        for s in levels:
            p = eng.clock(s, pop=len(eng.rxf) > 0)
            if p is not None:
                got.append(p * tick)
        res.append(got)
    return res


def high_frac(levels, pin):
    return sum((s >> pin) & 1 for s in levels) / len(levels)


# ---- targets
def uart(text, baud, gap_us=300.0):
    t = 1e6 / baud
    segs = [(1, 200.0)]
    for ch in text.encode():
        bits = [0] + [(ch >> k) & 1 for k in range(8)] + [1]
        segs += [(b, t) for b in bits] + [(1, gap_us)]
    return segs + [(1, 500.0)]


def manchester(bits, half, idle_after=10000.0):
    """DALI style: 1 = low then high, 0 = high then low (IEC 62386); idle high."""
    segs = [(1, 2000.0)]
    for b in bits:
        segs += [(0, half), (1, half)] if b else [(1, half), (0, half)]
    return segs + [(1, idle_after)]


def ir_nec(addr, cmd):
    """IR receiver output, active low: 9 ms mark, 4.5 ms space, 32 bits LSB first, final mark."""
    word = addr | ((~addr & 255) << 8) | (cmd << 16) | ((~cmd & 255) << 24)
    segs = [(1, 3000.0), (0, 9000.0), (1, 4500.0)]
    for k in range(32):
        segs += [(0, 562.0), (1, 1687.0 if (word >> k) & 1 else 562.0)]
    return segs + [(0, 562.0), (1, 5000.0)]


def free_clock(freq, duty=0.5, cycles=60):
    p = 1e6 / freq
    return [(1, p * duty), (0, p * (1 - duty))] * cycles


def i2c(transactions, half_us=5.0, gap_us=200.0):
    """Two pins: SCL bit 0, SDA bit 1 of the returned (level, us) pairs packed as values 0-3."""
    st = []                                        # (scl, sda, us)
    st.append((1, 1, gap_us))
    for data in transactions:
        st.append((1, 0, half_us))                 # START: SDA falls while SCL high
        for byte in data:
            for k in range(7, -1, -1):
                b = (byte >> k) & 1
                st += [(0, b, half_us), (1, b, half_us)]
            st += [(0, 0, half_us), (1, 0, half_us)]   # ACK from the slave
        st += [(0, 0, half_us), (1, 0, half_us), (1, 1, gap_us)]   # STOP: SDA rises while SCL high
    return [(scl | (sda << 1), us) for scl, sda, us in st]


def spi_mode0(data, half_us=0.5, gap_us=20.0):
    """Three pins: SCK bit 0, MOSI bit 1, CS bit 2 (active low)."""
    st = [(0, 0, 1, gap_us)]
    for byte in data:
        st.append((0, 0, 0, 2.0))
        for k in range(7, -1, -1):
            b = (byte >> k) & 1
            st += [(0, b, 0, half_us), (1, b, 0, half_us)]
        st += [(0, 0, 0, 2.0), (0, 0, 1, gap_us)]
    return [(sck | (mosi << 1) | (cs << 2), us) for sck, mosi, cs, us in st]


def led_1wire(pixels, t0h, t0l, t1h, t1l, byte_gap=0.0, pixel_gap=0.0, reset=300.0, frames=2, pins=1):
    """One-wire LED data: each bit a high pulse (short 0, long 1) then the rest of the bit low, MSB first; byte_gap and
    pixel_gap lengthen the low after a byte's or a pixel's last bit (the SP107E's firmware pauses: 1.4 us and 2.9 us
    lows measured 8 Nov 2026); a reset low between frames. pins > 1 puts the same signal on several pins (mirrored)."""
    one = (1 << pins) - 1
    segs = [(0, reset)]
    for _ in range(frames):
        for pi, px in enumerate(pixels):
            for bi, byte in enumerate(px):
                for k in range(7, -1, -1):
                    b = (byte >> k) & 1
                    hi, lo = (t1h, t1l) if b else (t0h, t0l)
                    if k == 0:
                        lo += pixel_gap if bi == len(px) - 1 else byte_gap
                    segs += [(one, hi), (0, lo)]
        segs.append((0, reset))
    return segs


SP107E = dict(t0h=0.36, t0l=0.85, t1h=0.885, t1l=0.36, byte_gap=0.55, pixel_gap=2.0)
RAINBOW = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0x55, 0xAA, 0x0F), (0xF0, 0x33, 0xCC), (0x81, 0x7E, 0x18)]

CASES = [
    # name, segments, tick us, {pin: expected kind}, expected extra check
    ("UART 115200 'Hello, world'", uart("Hello, world\r\n", 115200), 0.1, {0: "uart"}, ("baud", 0, 115200)),
    ("UART 9600 'AT+GMR'", uart("AT+GMR\r\n", 9600, 2000.0), 1.0, {0: "uart"}, ("baud", 0, 9600)),
    ("DALI forward frame x3", manchester([1] + [1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1], 1e6 / 2400) * 3, 1.0,
     {0: "manchester"}, ("bit_rate", 0, 1200)),
    # real senders are not exact, and the Pico's first pass measures at a 1 us tick
    ("UART 115200 on the 1 us tick", uart("Hello, world\r\n", 115200), 1.0, {0: "uart"}, ("baud", 0, 115200)),
    ("UART 57600, sender 3 % slow", uart("status?\r\n", 57600 * 0.97), 0.1, {0: "uart"}, ("baud", 0, 57600)),
    ("DALI, sender 8 % fast", manchester([1] + [0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 1, 0], 1e6 / 2400 / 1.08) * 3, 1.0,
     {0: "manchester"}, None),
    ("IR NEC frame", ir_nec(0x04, 0x08), 1.0, {0: "ir_nec"}, None),
    ("free-running clock 10 kHz", free_clock(10000), 1.0, {0: "clock_free"}, ("freq_hz", 0, 10000)),
    ("quiet high", [(1, 5000.0)], 1.0, {0: "quiet_high"}, None),
    ("quiet low", [(0, 5000.0)], 1.0, {0: "quiet_low"}, None),
    ("I2C 100 kHz, three writes", i2c([[0xA0, 0x00, 0x12, 0x34], [0xA0, 0x10, 0x55], [0xD0, 0x00]] * 2), 0.5,
     {0: "clock_idle_high"}, ("i2c", 0, 1)),
    ("SPI mode 0, 1 MHz", spi_mode0([0x9F, 0x00, 0x00, 0x00, 0xA5, 0x3C] * 4), 0.05, {0: "clock_idle_low"}, ("spi", 0, 2)),
    # one-wire LED data, measured at the chip clock (40 MHz: 0.025 us), as identify.py's second pass does
    # its 0-bits are 1.21 us and 1-bits 1.245 us (scope, 8 Nov), 3 ones in 24: the signal's own average is 824 kbit/s
    ("SP107E as measured: WS2811, red 0x70", led_1wire([(0x70, 0, 0)] * 8, **SP107E), 0.025, {0: "led_1wire"},
     ("bit_rate", 0, 824000)),
    ("WS2812B rainbow, half the bits 1", led_1wire(RAINBOW, 0.4, 0.85, 0.8, 0.45), 0.025, {0: "led_1wire"},
     ("bit_rate", 0, 800000)),
    ("WS2811 slow mode 400 kbit/s", led_1wire(RAINBOW, 0.5, 2.0, 1.2, 1.3), 0.025, {0: "led_1wire"}, ("bit_rate", 0, 400000)),
    ("SP107E pair: DAT and CLK mirrored", led_1wire([(0x70, 0, 0)] * 8, pins=2, **SP107E), 0.025,
     {0: "led_1wire", 1: "led_1wire"}, ("led_pair", 0, 1)),
]

ok = True
for name, segs, tick, want, extra in CASES:
    lv = expand(segs, tick)
    npins = 3 if "SPI" in name else 2 if ("I2C" in name or "pair" in name) else 1
    results = {}
    for pin in range(npins):
        lows, highs = measure(lv, pin, tick)
        results[pin] = ic.classify_pin(high_frac(lv, pin), lows, highs)
    good = all(results[p][0] == k for p, k in want.items())
    if extra:
        key, pin, val = extra
        if key in ("i2c", "spi", "led_pair"):
            buses = ic.pair_up(results)
            good &= any(b[0] == key and b[1] == pin and (val is None or b[2] == val) for b in buses)
        else:
            got = results[pin][2].get(key, 0)
            good &= abs(got - val) <= 0.03 * val
    ok &= good
    print("%-34s %s" % (name, "ok" if good else "WRONG"))
    for p in sorted(results):
        print("    pin %d: %-16s %s" % (p, results[p][0], results[p][1]))
    if extra and extra[0] in ("i2c", "spi", "led_pair"):
        for b in ic.pair_up(results):
            print("    bus: " + b[3])
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
