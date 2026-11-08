"""Blind identification: classify unknown pins from what the engines measured. Pure Python, no hardware: the Pico script
pico/identify.py feeds it, and model/test_identify.py checks it against the real engine programs on simulated targets.

Input per pin: the fraction of level samples that read high, the low-pulse widths and the high-pulse widths in
microseconds (programs/measure_pulse.asm and measure_high.asm). Output: a kind, a one-line description, and numbers.
Runs on MicroPython: no f-string formatting specs beyond %, no statistics module, no dataclasses."""

STD_BAUDS = (300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 57600, 76800, 115200, 230400, 250000,
             460800, 500000, 921600, 1000000)


def _median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else 0


def base_unit(widths):
    """The bit time T: the median of the shortest group of pulses (those within 1.5x the shortest that occurs twice)."""
    s = sorted(widths)
    if not s:
        return 0
    floor = s[0]
    for i in range(len(s) - 1):                 # ignore a single stray short glitch
        if s[i + 1] <= s[i] * 1.25:
            floor = s[i]
            break
    group = [w for w in s if floor <= w <= floor * 1.5]
    return _median(group) if group else floor


def multiples(widths, t, kmax=10, tol=0.2):
    """(fraction of widths within tol of k*t for some k in 1..kmax, the set of k values seen)."""
    if not widths or t <= 0:
        return 0.0, set()
    ks, hit = set(), 0
    for w in widths:
        k = int(w / t + 0.5)
        if 1 <= k <= kmax and abs(w - k * t) <= tol * t * max(1, k ** 0.5):
            hit += 1
            ks.add(k)
    return hit / len(widths), ks


def snap_baud(t_us):
    """Nearest standard baud rate within 5 %, else the measured rate."""
    if t_us <= 0:
        return 0, False
    b = 1e6 / t_us
    best = min(STD_BAUDS, key=lambda s: abs(s - b))
    return (best, True) if abs(best - b) <= 0.05 * best else (int(b + 0.5), False)


def _spread(v):
    return (max(v) / min(v)) if v and min(v) > 0 else 0


def classify_pin(high_frac, lows, highs):
    """Returns (kind, text, info). kind: quiet_high, quiet_low, quiet_mixed, ir_nec, onewire, manchester, uart,
    clock_idle_high, clock_idle_low, clock_free, data."""
    n = len(lows) + len(highs)
    info = {"lows": len(lows), "highs": len(highs), "low_med": _median(lows)}
    if n == 0:
        if high_frac >= 0.9:
            return "quiet_high", "quiet, idles high (pull-up, an idle bus or a driven high)", info
        if high_frac <= 0.1:
            return "quiet_low", "quiet, low (not connected, pulled down or driven low)", info
        return "quiet_mixed", "slow changes only (%.0f %% high)" % (100 * high_frac), info
    idle_high = high_frac >= 0.5
    if idle_high and lows:
        lead = [w for w in lows if 8000 <= w <= 10000]
        marks = [w for w in lows if 400 <= w <= 750]
        if lead and len(marks) >= 8:
            info["leader_us"] = lead[0]
            return "ir_nec", "IR receiver output, NEC (9 ms leader, 562 us marks)", info
    allw = lows + highs
    uart = _uart(idle_high, lows, info)
    if uart:
        return uart
    if idle_high and lows:
        reset = [w for w in lows if 400 <= w <= 960]
        tiny = [w for w in lows if w <= 15]            # write-1 / read slots: no UART has these beside 480 us lows
        if reset and len(tiny) >= 2 and len(reset) <= len(lows) // 3 + 1:
            return "onewire", "1-Wire (480 us reset pulses, short time slots)", info
    t = base_unit(allw)
    info["t_us"] = t
    # Manchester: every pulse inside a frame is T or 2T (long idle gaps between frames are left out)
    inside = [w for w in allw if w <= 2.6 * t]
    frac, ks = multiples(inside, t, kmax=2, tol=0.15)
    if t > 0 and len(inside) >= 8 and frac >= 0.9 and ks == {1, 2}:
        lows_k = multiples([w for w in lows if w <= 2.6 * t], t, kmax=2, tol=0.15)[1]
        if lows_k == {1, 2} and len(inside) >= 0.8 * len(allw) and _uart_gaps(lows, t) is False:
            info["bit_rate"] = int(1e6 / (2 * t) + 0.5)
            if 380 <= t <= 450:
                return "manchester", "Manchester at %d bit/s: DALI (half-bit %.0f us)" % (info["bit_rate"], t), info
            return "manchester", "Manchester at %d bit/s (half-bit %.2f us)" % (info["bit_rate"], t), info
    # clocks: many pulses of both kinds, tight once the long idle gaps between bursts are set aside
    lo_in, lo_idle = _split_idle(lows)
    hi_in, hi_idle = _split_idle(highs)
    if len(lo_in) >= 16 and len(hi_in) >= 16 and _spread(lo_in) <= 1.3 and _spread(hi_in) <= 1.3:
        period = _median(lo_in) + _median(hi_in)
        info["freq_hz"] = int(1e6 / period + 0.5)
        if hi_idle and not lo_idle:
            return "clock_idle_high", "clock in bursts, idles high, %s (I2C SCL, or SPI mode 2/3)" % _hz(info["freq_hz"]), info
        if lo_idle and not hi_idle:
            return "clock_idle_low", "clock in bursts, idles low, %s (SPI SCK mode 0/1)" % _hz(info["freq_hz"]), info
        if not lo_idle and not hi_idle:
            return "clock_free", "free-running clock, %s, duty %.0f %%" % (
                _hz(info["freq_hz"]), 100 * _median(hi_in) / period), info
    return "data", "active, irregular (%d low, %d high pulses, shortest %.2f us), idles %s" % (
        len(lows), len(highs), min(allw), "high" if idle_high else "low"), info


def _uart(idle_high, lows, info):
    """UART: idles high, every low is a whole number of bit times (start bit plus zero bits, at most 9)."""
    if not (idle_high and lows):
        return None
    tl = base_unit(lows)
    frac, ks = multiples(lows, tl, kmax=10, tol=0.2)
    if frac >= 0.9 and max(lows) <= 10.5 * tl and (max(ks) >= 3 or _uart_gaps(lows, tl)):
        baud, std = snap_baud(tl)
        info["t_us"], info["baud"] = tl, baud
        return "uart", "UART, %d baud%s, idles high (start bit %.2f us)" % (
            baud, "" if std else " (not a standard rate)", tl), info
    return None


def _split_idle(widths):
    """(pulses inside bursts, idle gaps): a gap is over 3x the median and at most a fifth of the pulses."""
    if not widths:
        return [], []
    m = _median(widths)
    long_ = [w for w in widths if w > 3 * m]
    if len(long_) > len(widths) // 5 + 1:
        return widths, []
    return [w for w in widths if w <= 3 * m], long_


def _uart_gaps(lows, t):
    """True if some lows are 3T or longer (a UART byte with zero runs): Manchester never has them."""
    return any(w >= 2.8 * t for w in lows)


def _hz(f):
    if f >= 1000000:
        return "%.2f MHz" % (f / 1e6)
    if f >= 1000:
        return "%.1f kHz" % (f / 1e3)
    return "%d Hz" % f


def pair_up(results):
    """results: {pin: (kind, text, info)}. Returns lines describing buses made of several pins."""
    out = []
    clocks_h = [p for p, r in results.items() if r[0] == "clock_idle_high"]
    clocks_l = [p for p, r in results.items() if r[0] == "clock_idle_low"]
    # SDA on its own can pass for a UART or Manchester line (its lows are whole bit times): any active pin that idles
    # high is a candidate partner for a clock that idles high
    data_h = [p for p, r in results.items() if r[0] in ("data", "uart", "manchester") and r[2].get("lows", 0) > 0]
    for c in clocks_h:
        partners = [d for d in data_h if d != c]
        if partners:
            out.append(("i2c", c, partners[0],
                        "I2C bus likely: SCL pin %d, SDA pin %d (%s)" % (c, partners[0], _hz(results[c][2]["freq_hz"]))))
    for c in clocks_l:
        period = 1e6 / results[c][2]["freq_hz"]
        # chip select: idles high, drops low for a whole transfer (several clock periods), far fewer times than the clock
        cs = [p for p, r in results.items() if p != c and r[2].get("lows", 0) > 0 and r[2].get("low_med", 0) >= 6 * period]
        data = [p for p, r in results.items() if p != c and p not in cs and r[0] in ("data", "quiet_low", "quiet_high")]
        out.append(("spi", c, cs[0] if cs else None, "SPI likely: SCK pin %d (%s), chip select %s, data among pins %s" % (
            c, _hz(results[c][2]["freq_hz"]), ("pin %d" % cs[0]) if cs else "not seen",
            ", ".join(str(p) for p in data) or "none seen")))
    quiet_h = sorted(p for p, r in results.items() if r[0] == "quiet_high")
    if len(quiet_h) >= 2 and not clocks_h:
        out.append(("idle_pair", quiet_h[0], quiet_h[1],
                    "pins %s idle high: possibly an idle I2C bus (pull-ups); a scan can tell (PROBE)" % ", ".join(str(p) for p in quiet_h)))
    return out
