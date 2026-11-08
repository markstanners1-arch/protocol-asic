"""DS18B20 temperature sensor over Dallas 1-Wire, from the Pico: engine B runs programs/onewire.asm on engine pin 3
(Mojo shield hole 32, inner). The sensor module: DAT -> hole 32, VCC -> Pico 3V3 (pin 36), GND -> common ground. The
line needs a pull-up of about 4.7 k to 3.3 V (most DS18B20 modules have one on board; a bare sensor needs one fitted).
Program checked against a modelled DS18B20 (model/test_onewire.py). The test, in order:
  1. reset: a presence pulse
  2. READ ROM: family code 0x28 and the ROM's CRC-8
  3. CONVERT T, timed by polling read slots (a 12-bit conversion takes up to 750 ms)
  4. READ SCRATCHPAD: 9 bytes, CRC-8, temperature in a plausible range (0 to 45 C)
  5. MATCH ROM with the ROM just read: the scratchpad again; with one bit of the ROM changed: silence (all 0xFF)
  6. WRITE SCRATCHPAD (TH, TL kept, config kept) with new alarm bytes, read back, then the original bytes put back
  7. a reading every second for SECONDS seconds: hold the sensor between finger and thumb when the script says HOLD
     and let go at LET GO; the reading must rise by at least 1 C while held
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script onewire.py -Seconds 60 -Pre "CHIP_HZ=40_000_000"
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
try:
    SECONDS
except NameError:
    SECONDS = 30
PIN = 3
ENG = ENG_B
errors = 0


def check(what, ok, info=""):
    global errors
    if not ok:
        errors += 1
    print("  %-58s %s %s" % (what, "ok" if ok else "WRONG", info))
    return ok


def crc8(data):
    c = 0
    for b in data:
        for _ in range(8):
            mix = (c ^ b) & 1
            c >>= 1
            if mix:
                c ^= 0x8C
            b >>= 1
    return c


chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)
print("\n==== DS18B20 over 1-Wire: engine B, engine pin %d ====" % PIN)
print("  chip ID 0x%04X" % chip.chip_id())
L = LABELS["onewire"]
words, wb, wt = PROGRAMS["onewire"]
chip.stop(ENG_A)
chip.stop(ENG)
chip.write(ENG, R_FILTER, 0)
chip.load_program(ENG, words)
chip.write(ENG, R_CLKDIV, round(CHIP_HZ * 2e-6) - 1)                     # one tick = 2 us
chip.write(ENG, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG, R_OUTCFG, PIN | (1 << 5) | (PIN << 10))                  # out_base = set_base = the pin, out_count 1
chip.write(ENG, R_MISC, 1 | (1 << 11) | (1 << 12))                       # set_count 1, out_right, in_right
chip.write(ENG, R_INCFG, PIN)
chip.drain(ENG)
chip.start(ENG)
time.sleep_ms(5)


def cmd(word):
    chip.write(ENG, R_TX, word)
    t = time.ticks_ms()
    while chip.rx_level(ENG) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine B: is the chip loaded?")
    return chip.read(ENG, R_RX)


def reset():
    return (cmd(L["reset"]) >> 15) == 0                                    # True = presence pulse


def xfer(b):
    return cmd(b << 5 | L["xfer"]) >> 8


def write(*data):
    for b in data:
        xfer(b)


def read(n):
    return [xfer(0xFF) for _ in range(n)]


def temp_of(sp):
    raw = sp[0] | sp[1] << 8
    if raw & 0x8000:
        raw -= 0x10000
    return raw / 16.0


def convert():
    """SKIP ROM, CONVERT T; poll read slots until done. Returns ms taken, or None if it never finished."""
    reset(); write(0xCC, 0x44)
    t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t) < 1500:
        if xfer(0xFF) == 0xFF:
            return time.ticks_diff(time.ticks_ms(), t)
    return None


def scratchpad(rom=None):
    reset()
    if rom is None:
        write(0xCC, 0xBE)
    else:
        write(0x55, *rom); write(0xBE)
    return read(9)


# 1. presence
present = reset()
check("1. reset: presence pulse", present, "" if present else "(no device: check DAT on hole 32, VCC, GND, pull-up)")
if present:
    # 2. ROM
    write(0x33)
    rom = read(8)
    check("2. READ ROM: family 0x28, CRC-8 good", rom[0] == 0x28 and crc8(rom[:7]) == rom[7],
          " ".join("%02x" % b for b in rom))
    # 3. conversion
    ms = convert()
    check("3. CONVERT T finished, under 1000 ms", ms is not None and ms < 1000, "%s ms" % ms)
    # 4. scratchpad
    sp = scratchpad()
    t0 = temp_of(sp)
    check("4. READ SCRATCHPAD: CRC-8 good", crc8(sp[:8]) == sp[8], " ".join("%02x" % b for b in sp))
    check("   temperature plausible (0 to 45 C)", 0 <= t0 <= 45 and t0 != 85.0, "%.4f C" % t0)
    # 5. match ROM
    sp2 = scratchpad(rom)
    check("5. MATCH ROM (this sensor): scratchpad, CRC-8 good", crc8(sp2[:8]) == sp2[8] and sp2[:2] == sp[:2])
    wrong = list(rom); wrong[3] ^= 0x01
    check("   MATCH ROM (one bit changed): silent", scratchpad(wrong) == [0xFF] * 9)
    # 6. write scratchpad, read back, restore
    th, tl, cfg = sp[2], sp[3], sp[4]
    reset(); write(0xCC, 0x4E, 0x5A, 0xA5, cfg)
    sp3 = scratchpad()
    check("6. WRITE SCRATCHPAD: alarm bytes 5A A5 read back", sp3[2:4] == [0x5A, 0xA5] and crc8(sp3[:8]) == sp3[8])
    reset(); write(0xCC, 0x4E, th, tl, cfg)
    sp4 = scratchpad()
    check("   original alarm bytes put back", sp4[2:5] == [th, tl, cfg], "%02x %02x %02x" % (th, tl, cfg))
    # 7. readings, held and let go
    print("\n  7. a reading a second for %d s" % SECONDS)
    temps = []
    hold_at, go_at = SECONDS // 3, 2 * SECONDS // 3
    for s in range(SECONDS):
        t = time.ticks_ms()
        if s == hold_at:
            print("  >>> HOLD the sensor between finger and thumb now")
        if s == go_at:
            print("  >>> LET GO")
        ok = convert() is not None
        sp = scratchpad()
        good = ok and crc8(sp[:8]) == sp[8]
        temps.append(temp_of(sp) if good else None)
        print("  %3d s  %s" % (s, ("%.4f C" % temps[-1]) if good else "bad read"))
        time.sleep_ms(max(0, 1000 - time.ticks_diff(time.ticks_ms(), t)))
    good = [x for x in temps if x is not None]
    check("   every reading's CRC good", len(good) == len(temps), "%d of %d" % (len(good), len(temps)))
    before = [x for x in temps[:hold_at] if x is not None]
    held = [x for x in temps[hold_at:go_at] if x is not None]
    if before and held:
        rise = max(held) - min(before)
        check("   held: the reading rose at least 1 C", rise >= 1.0, "%.2f C to %.2f C" % (min(before), max(held)))
chip.stop(ENG)
print("\n==== %s (%d problems) ====" % ("FAIL" if errors else "PASS", errors))
