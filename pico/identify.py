"""Blind identification: connect the chip's input pins to an unknown 3.3 V board and let the engines work out what is on
each wire. Listen only unless PROBE is set. The deciding is done by pico/identify_core.py (tested on simulated targets by
model/test_identify.py); this script only runs the engines and collects what they measure.
  1. ID register: how many engines there are to measure with
  2. levels: each input pin sampled many times (programs/read_pins.asm)
  3. pulses: every pin's low pulses (measure_pulse.asm) and high pulses (measure_high.asm), several pins at once, one
     engine per pin, at a 1 us tick; pins with pulses under 50 us are measured again at the chip clock for precision
  4. each pin classified, then pins paired into buses (I2C, SPI)
  5. PROBE only: an I2C address scan on a pair found idle high, both ways round (open drain: the chip only ever pulls low)
The handler checks the target is 3.3 V logic first. Never set PROBE on a board where an idle-high line might be a push-pull
output: pulling it low fights the driver.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script identify.py -Seconds 90 [-Pre "CHIP_HZ=12_000_000;PROBE=True"]"""
import time
from chip_host import Chip, wrap_reg, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER, R_STATUS
from programs import PROGRAMS, LABELS
import identify_core as ic

try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 50_000_000            # the Mojo build; the MachXO3L kit runs at 12 MHz
try:
    PROBE
except NameError:
    PROBE = False
try:
    WINDOW_MS
except NameError:
    WINDOW_MS = 400
try:
    SELFTEST
except NameError:
    SELFTEST = False
# SELFTEST: the Pico makes two known signals while it listens, and the answers are checked at the end (Mojo bench sheet,
# section 14): a 10 kHz PWM clock on GP2 (already wired to engine pin 15, hole 57) and a 115200 baud UART from GP4
# (UART1 TX, one extra lead to engine pin 16, hole 58), "Hello, world" every 20 ms.
if SELFTEST:
    from machine import Pin, PWM, UART, Timer
    pwm = PWM(Pin(2)); pwm.freq(10000); pwm.duty_u16(32768)
    uart1 = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))
    tim = Timer(period=20, mode=Timer.PERIODIC, callback=lambda t: uart1.write(b"Hello, world\r\n"))
PINS = list(range(0, 8)) + list(range(15, 20))      # every pin the engines can read (8-13 are outputs only)

chip = Chip(CHIP_HZ)
cid = chip.chip_id()
neng = cid & 15
print("==== identify: what is on these wires? ====")
print("chip ID 0x%04X: %d engines, clock %.0f MHz; %s" % (cid, neng, CHIP_HZ / 1e6, "PROBE on" if PROBE else "listening only"))
if not 1 <= neng <= 8 or (cid >> 4) != 2:
    print("FAIL: the ID register is wrong (check the SPI leads with programs/read_pins.asm)")
    raise SystemExit
for e in range(neng):
    chip.stop(e)
chip.write(0, R_FILTER, 0)


def setup(eng, name, in_base, clkdiv):
    w, b, t = PROGRAMS[name]
    chip.stop(eng)
    chip.load_program(eng, w)
    chip.write(eng, R_CLKDIV, clkdiv)
    chip.write(eng, R_WRAP, wrap_reg(0, b, t))
    chip.write(eng, R_OUTCFG, 0); chip.write(eng, R_MISC, 0); chip.write(eng, R_INCFG, in_base)
    chip.drain(eng)


# ---- 2. levels
def levels():
    frac = {}
    for base, pins in ((0, range(0, 8)), (15, range(15, 20))):
        setup(0, "read_pins", base, 0)
        chip.start(0)
        ones = {p: 0 for p in pins}
        n = 0
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 150:
            v = chip.read(0, R_RX)
            n += 1
            for p in pins:
                ones[p] += (v >> (p - base)) & 1
        chip.stop(0)
        for p in pins:
            frac[p] = ones[p] / n
    return frac


# ---- 3. pulses
def pulses(pins, name, clkdiv, ms):
    """One engine per pin, all running together; returns {pin: [widths in us]}."""
    """One engine per pin, all running together; returns {pin: (raw tick counts, us per tick)}. Counts stay whole numbers
    (a float is a heap object in MicroPython) and at most MAXN are kept per pin."""
    tick_us = (clkdiv + 1) * 1e6 / CHIP_HZ
    for e, p in enumerate(pins):
        setup(e, name, p, clkdiv)
    for e in range(len(pins)):
        chip.start(e)
    got = {p: [] for p in pins}
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        for e, p in enumerate(pins):
            if chip.read(e, R_STATUS) & 0x70:
                v = chip.read(e, R_RX)
                if len(got[p]) < MAXN:
                    got[p].append(v)
    for e in range(len(pins)):
        chip.stop(e)
    return {p: (got[p], tick_us) for p in pins}


def us(entry):
    counts, tick = entry
    return [c * tick for c in counts]


def shortest_us(p):
    c = low[p][0] + high[p][0]
    return min(c) * low[p][1] if c else None


MAXN = 300
lv = levels()
coarse = round(CHIP_HZ / 1e6) - 1
low, high = {}, {}
for i in range(0, len(PINS), neng):
    group = PINS[i:i + neng]
    low.update(pulses(group, "measure_pulse", coarse, WINDOW_MS))
    high.update(pulses(group, "measure_high", coarse, WINDOW_MS))
fast = [p for p in PINS if shortest_us(p) is not None and shortest_us(p) < 50]
for i in range(0, len(fast), neng):                # again at the chip clock: 16-bit counts saturate at 65535 ticks
    group = fast[i:i + neng]
    low.update(pulses(group, "measure_pulse", 0, WINDOW_MS))
    high.update(pulses(group, "measure_high", 0, WINDOW_MS))

# ---- 4. classify, one pin at a time so only one pin's widths are ever floats
results = {}
for p in PINS:
    results[p] = ic.classify_pin(lv[p], us(low[p]), us(high[p]))
print("\nPer pin (%d ms per polarity%s):" % (WINDOW_MS, "; pins %s measured again at the chip clock" % fast if fast else ""))
for p in PINS:
    k, text, info = results[p]
    print("  pin %2d  %3.0f %% high  %s" % (p, 100 * lv[p], text))
buses = ic.pair_up(results)
print("\nBuses:")
for b in buses:
    print("  " + b[3])
if not buses:
    print("  none found")

# ---- 5. probe (opt in)
GUESS = {0x20: "PCF8574 / MCP23008 I/O expander", 0x27: "PCF8574 LCD backpack", 0x3C: "SSD1306 OLED", 0x3D: "SSD1306 OLED",
         0x40: "INA219, Si7021 or HTU21D", 0x48: "ADS1115, PCF8591 or TMP102", 0x57: "AT24C32 on a DS3231 module",
         0x60: "MCP4725 DAC", 0x61: "MCP4725 DAC", 0x68: "DS3231 RTC or MPU6050", 0x69: "MPU6050 (AD0 high)",
         0x76: "BMP280 / BME280", 0x77: "BMP180 / BMP280 / BME280"}


def i2c_scan(scl, sda):
    L = LABELS["i2c_master"]
    w, b, t = PROGRAMS["i2c_master"]
    chip.stop(0)
    chip.load_program(0, w)
    chip.write(0, R_CLKDIV, round(CHIP_HZ / (10 * 100000)) - 1)            # 100 kHz
    chip.write(0, R_WRAP, wrap_reg(0, b, t))
    chip.write(0, R_OUTCFG, sda | (1 << 5) | (sda << 10))
    chip.write(0, R_MISC, 1 | (scl << 3) | (1 << 8) | (1 << 10) | (1 << 13))  # side-set on SCL's direction: open drain
    chip.write(0, R_INCFG, sda)
    chip.drain(0)
    chip.start(0)
    time.sleep_ms(5)

    def xfer(word):
        chip.write(0, R_TX, word)
        t0 = time.ticks_ms()
        while chip.rx_level(0) == 0:
            if time.ticks_diff(time.ticks_ms(), t0) > 100:
                return None
        return chip.read(0, R_RX)

    found = []
    for a in range(0x08, 0x78):
        chip.write(0, R_TX, L["start"] << 11); time.sleep_ms(1)
        r = xfer(L["xfer"] << 11 | (a << 1) << 3 | 1 << 2)
        chip.write(0, R_TX, L["stop"] << 11); time.sleep_ms(1)
        if r == (a << 1) << 1:
            found.append(a)
    chip.stop(0)
    return found


if PROBE:
    print("\nProbe (PROBE set): I2C scan, open drain, 100 kHz, on pairs that idle high and are quiet")
    pairs = [(b[1], b[2]) for b in buses if b[0] == "idle_pair"]
    for scl, sda in pairs:
        for c, d in ((scl, sda), (sda, scl)):
            f = i2c_scan(c, d)
            if f:
                print("  SCL pin %d, SDA pin %d: %s" % (c, d, ", ".join("0x%02X %s" % (a, GUESS.get(a, "")) for a in f)))
                break
        else:
            print("  pins %d, %d: nothing answered either way round" % (scl, sda))
    if not pairs:
        print("  no quiet idle-high pair to scan (an active bus is never probed)")
if SELFTEST:
    tim.deinit(); pwm.deinit()
    Pin(2, Pin.IN)                                  # back to a plain input, as regression.py expects
    print("\nSelf-test (known signals from the Pico):")
    want = [(15, "clock_free", "freq_hz", 10000, "10 kHz clock from GP2"),
            (16, "uart", "baud", 115200, "115200 baud UART from GP4")]
    bad = 0
    for pin, kind, key, val, what in want:
        k, text, info = results[pin]
        good = k == kind and abs(info.get(key, 0) - val) <= 0.03 * val
        bad += 0 if good else 1
        print("  pin %2d  want %-26s got %-16s %s" % (pin, what, k, "ok" if good else "WRONG"))
    print("\nFAIL: %d of %d self-test signals wrong" % (bad, len(want)) if bad else "\nPASS: identify self-test, both known signals named")
else:
    print("\nPASS: identify finished")
