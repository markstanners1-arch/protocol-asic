"""DS3231 clock module from the Pico: engine A runs programs/i2c_master.asm (SCL = engine pin 2 = J4-10, SDA = pin 3 = J4-13,
100 kHz) to the RTC at 0x68 and the AT24C32 EEPROM (4 KB, 2 address bytes, 32-byte pages) that rides on the same module at 0x57.
Checked against a modelled device; not yet run on hardware. The module sits on the same two wires as the AT24C256 (0x50):
both can stay. Wiring (sheet section 11): module VCC -> J4-1 or J4-2 (3.3 V only: its pull-ups go to VCC), GND -> the negative rail (wired to
J4-11 or 12), SCL -> J4-10, SDA -> J4-13; 32K and SQW left open. At 3.3 V the module's LIR2032 charge path (VCC, diode, 200 ohm)
sits below a 3 V cell and does nothing, so a plain CR2032 is safe in it at 3.3 V (never 5 V with a CR2032 fitted).

Two common devices answer at 0x68: this DS3231 and the MPU6050 on a GY-521 module (whose AD0 low gives 0x68 as well). The script
tells them apart in two ways: the MPU6050's WHO_AM_I register 0x75 reads 0x68 (its own address; the DS3231 has only registers
0x00-0x12 and its pointer wraps, so 0x75 there comes back as one of its own small time or alarm registers, not 0x68); and the
DS3231's seconds register runs: read twice two seconds apart it must advance, while an MPU6050's register 0x00 is a static
self-test value, so the running clock is the check that settles it. Its control/status pair 0x0E/0x0F is printed too (0x0E power-on
default 0x1C; 0x0F bit 7 OSF = the oscillator stopped since the time was last set, so the time is not to be trusted).

The test, in order, each line with its expected readback:
  1. scan: 0x50 (the AT24C256 module, if still on the bus), 0x57 (the DS3231 module's AT24C32) and 0x68 (the DS3231) must answer
  2. who is at 0x68: register 0x75 must NOT read 0x68 (that would be an MPU6050)
  3. time registers 0x00-0x06 read, 2 s pause, read again: the seconds must have advanced by 2 (1 to 3 allowed: the
     scripted check), hours in 24-hour mode (bit 6 of 0x02 clear)
  4. temperature 0x11/0x12: the MSB is a signed degree count, the top two bits of the LSB are quarters; expect the room (10 to 35 C)
  5. the AT24C32 at 0x57: the at24c.py logic with 2 address bytes and an 8-byte write, then the proof that the high address byte
     is used: a different pattern at 0x0FF0 (top of the 4 KB) must not disturb 0x0010, and both are put back as found
  6. SET_TIME: only if set (a tuple (year, month, day, hours, minutes, seconds, weekday 1-7)), the time is written and OSF cleared
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script ds3231.py -Seconds 20"""
import time
from chip_host import Chip, wrap_reg, ENG_A, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

try: SET_TIME
except NameError: SET_TIME = None      # e.g. (2026, 11, 5, 14, 30, 0, 4) = Thursday 5 Nov 2026 14:30:00 (weekday 1 = Monday by this script's convention)
CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
RTC, EEPROM, OTHER = 0x68, 0x57, 0x50
MEM, HIGH, N = 0x0010, 0x0FF0, 8      # the AT24C32 is 4 KB: 0x0FF0 is its top page; 0x7FF0 would alias onto 0x0FF0

chip = Chip(CHIP_HZ)
L = LABELS["i2c_master"]
words, wb, wt = PROGRAMS["i2c_master"]
chip.stop(ENG_A)
chip.write(ENG_A, R_FILTER, 0)
chip.load_program(ENG_A, words)
chip.write(ENG_A, R_CLKDIV, round(CHIP_HZ / (10 * 100000)) - 1)                 # 10 ticks a bit: 100 kHz
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, SDA | (1 << 5) | (SDA << 10))                        # out and set = SDA
chip.write(ENG_A, R_MISC, 1 | (SCL << 3) | (1 << 8) | (1 << 10) | (1 << 13))     # set_count 1, side-set SCL (directions)
chip.write(ENG_A, R_INCFG, SDA)
chip.drain(ENG_A)
chip.start(ENG_A)
time.sleep_ms(5)


def xfer(word):
    chip.write(ENG_A, R_TX, word)
    t = time.ticks_ms()
    while chip.rx_level(ENG_A) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine A: is the kit loaded?")
    return chip.read(ENG_A, R_RX)


def start():
    chip.write(ENG_A, R_TX, L["start"] << 11); time.sleep_ms(1)


def stop():
    chip.write(ENG_A, R_TX, L["stop"] << 11); time.sleep_ms(1)


def send(b):
    """One byte out; True if the slave acked (the reply is the byte as it went on the wire, then a 0 ACK bit)."""
    return xfer(L["xfer"] << 11 | b << 3 | 1 << 2) == b << 1


def recv(ack):
    return (xfer(L["xfer"] << 11 | 0xFF << 3 | (0 if ack else 1) << 2) >> 1) & 0xFF


def probe(addr):
    start(); ok = send(addr << 1); stop()
    return ok


def reg_read(dev, reg, n):
    """n bytes from register reg of a device with a one-byte register pointer (the DS3231)."""
    start(); ok = send(dev << 1) and send(reg)
    start(); ok = ok and send(dev << 1 | 1)
    out = [recv(i < n - 1) for i in range(n)]
    stop()
    return out if ok else None


def reg_write(dev, reg, data):
    start(); ok = send(dev << 1) and send(reg)
    for d in data:
        ok = ok and send(d)
    stop()
    return ok


def bcd(b):
    return (b >> 4) * 10 + (b & 15)


def to_bcd(v):
    return (v // 10) << 4 | (v % 10)


def hexs(bs):
    return " ".join("%02X" % b for b in bs)


def clock(regs):
    """(seconds of the day, text) from the seven time registers."""
    s, m = bcd(regs[0] & 0x7F), bcd(regs[1] & 0x7F)
    h12 = regs[2] & 0x40
    h = bcd(regs[2] & 0x1F) % 12 + (12 if regs[2] & 0x20 else 0) if h12 else bcd(regs[2] & 0x3F)
    d, mo, y = bcd(regs[4] & 0x3F), bcd(regs[5] & 0x1F), 2000 + bcd(regs[6]) + (100 if regs[5] & 0x80 else 0)
    return h * 3600 + m * 60 + s, "%02d:%02d:%02d %02d/%02d/%d weekday %d%s" % (h, m, s, d, mo, y, regs[3] & 7, " (12-hour mode)" if h12 else "")


# ---- the AT24C32 part: the at24c.py logic with 2 address bytes
def mem_addr(mem):
    return send(mem >> 8) and send(mem & 255)


def write_page(dev, mem, data):
    start(); ok = send(dev << 1) and mem_addr(mem)
    for d in data:
        ok = ok and send(d)
    stop()
    return ok


def wait_write(dev):
    """ACK polling: a busy EEPROM does not answer its address. Milliseconds until it does (None if it never does)."""
    t = time.ticks_ms()
    while True:
        if probe(dev):
            return time.ticks_diff(time.ticks_ms(), t)
        if time.ticks_diff(time.ticks_ms(), t) > 50:
            return None


def read_seq(dev, mem, n):
    start(); ok = send(dev << 1) and mem_addr(mem)
    start(); ok = ok and send(dev << 1 | 1)
    out = [recv(i < n - 1) for i in range(n)]
    stop()
    return out if ok else None


ok = True
print("==== DS3231 module from the Pico: engine A I2C master, SCL pin %d (J4-10), SDA pin %d (J4-13), 100 kHz ====" % (SCL, SDA))

# ---- 1. scan
found = [a for a in range(0x08, 0x78) if probe(a)]
print("answered:               %s   (expect 0x57 and 0x68 from the module, plus 0x50 if the AT24C256 module is still on the bus)" % (" ".join("0x%02X" % a for a in found) or "nothing"))
if RTC not in found:
    print("FAIL: nothing at 0x68: check the module's VCC (3.3 V), ground to the kit, SCL J4-10, SDA J4-13; nothing at all = the bus (pull-ups, an unpowered instrument clamping it)")
    chip.stop(ENG_A)
    raise SystemExit
ok &= EEPROM in found

# ---- 2. who is at 0x68
who = reg_read(RTC, 0x75, 1)
ctl = reg_read(RTC, 0x0E, 2)
is_mpu = who is not None and who[0] in (0x68, 0x69, 0x70, 0x71, 0x72, 0x98)
print("register 0x75:          %s   %s" % (hexs(who) if who else "READ FAILED", "an MPU6050 (WHO_AM_I = 0x68): that is the GY-521, not the clock" if is_mpu else "not an MPU6050 WHO_AM_I: a DS3231 (its pointer wrapped)"))
ok &= who is not None and not is_mpu
if ctl:
    print("control 0x0E, status 0x0F: %s   (power-on 1C 88; status bit 7 OSF %s)" % (hexs(ctl), "SET: the oscillator has stopped since the time was last set, set SET_TIME" if ctl[1] & 0x80 else "clear: the time has run since it was set"))

# ---- 3. the clock runs
t1 = reg_read(RTC, 0x00, 7)
time.sleep(2)
t2 = reg_read(RTC, 0x00, 7)
if t1 and t2:
    s1, txt1 = clock(t1)
    s2, txt2 = clock(t2)
    adv = (s2 - s1) % 86400
    print("time registers 0x00-06: %s   = %s" % (hexs(t1), txt1))
    print("two seconds later:      %s   = %s" % (hexs(t2), txt2))
    print("seconds advanced by:    %d   %s" % (adv, "ok (2 +-1)" if 1 <= adv <= 3 else "WRONG: the clock is not running" if adv == 0 else "WRONG"))
    ok &= 1 <= adv <= 3
    h12 = t1[2] & 0x40
    print("hour mode:              %s" % ("24-hour, ok" if not h12 else "12-hour (bit 6 of 0x02): works, but set SET_TIME to put it in 24-hour mode"))
else:
    print("time registers:         READ FAILED"); ok = False

# ---- 4. temperature
tmp = reg_read(RTC, 0x11, 2)
if tmp:
    msb = tmp[0] - 256 if tmp[0] & 0x80 else tmp[0]
    degc = msb + (tmp[1] >> 6) * 0.25
    print("temperature 0x11/0x12:  %s   = %.2f C   %s (a new conversion every 64 s)" % (hexs(tmp), degc, "ok: a room" if 10 <= degc <= 35 else "WRONG: not a room temperature"))
    ok &= 10 <= degc <= 35
else:
    print("temperature:            READ FAILED"); ok = False

# ---- 5. the AT24C32 at 0x57
if EEPROM in found:
    before = read_seq(EEPROM, MEM, N)
    print("AT24C32 at 0x%04X as found: %s" % (MEM, hexs(before) if before else "READ FAILED"))
    ok &= before is not None
    seed = time.ticks_ms() & 0xFF
    pattern = [((i * 37) + seed) & 0xFF for i in range(N)]
    if pattern == before:
        pattern = [b ^ 0xFF for b in pattern]
    w = write_page(EEPROM, MEM, pattern); cycle = wait_write(EEPROM)
    print("wrote (seed %02X):       %s   page write %s, write cycle %s" % (seed, hexs(pattern), "acked" if w else "NOT ACKED", ("%d ms (expect under 10)" % cycle) if cycle is not None else "never finished"))
    ok &= w and cycle is not None
    after = read_seq(EEPROM, MEM, N)
    print("sequential read back:   %s   %s" % (hexs(after) if after else "READ FAILED", "ok" if after == pattern else "WRONG"))
    ok &= after == pattern
    hb = read_seq(EEPROM, HIGH, N)
    pat2 = pattern[::-1]
    if pat2 == hb:
        pat2 = [b ^ 0xFF for b in pat2]
    w2 = write_page(EEPROM, HIGH, pat2); c2 = wait_write(EEPROM)
    top = read_seq(EEPROM, HIGH, N)
    low = read_seq(EEPROM, MEM, N)
    print("top of the 4 KB 0x%04X:  %s   %s (wrote %s)" % (HIGH, hexs(top) if top else "READ FAILED", "ok" if top == pat2 else "WRONG", hexs(pat2)))
    print("0x%04X unchanged:       %s   %s" % (MEM, hexs(low) if low else "READ FAILED", "ok: the high address byte is used" if low == pattern else "WRONG: the high address byte is being ignored"))
    ok &= w2 and c2 is not None and top == pat2 and low == pattern
    write_page(EEPROM, MEM, before); wait_write(EEPROM)
    write_page(EEPROM, HIGH, hb); wait_write(EEPROM)
    r1, r2 = read_seq(EEPROM, MEM, N), read_seq(EEPROM, HIGH, N)
    print("both put back:          %s / %s   %s" % (hexs(r1) if r1 else "READ FAILED", hexs(r2) if r2 else "READ FAILED", "ok" if r1 == before and r2 == hb else "WRONG"))
    ok &= r1 == before and r2 == hb
else:
    print("AT24C32:                nothing at 0x57: the module's EEPROM did not answer (its A0-A2 pads are pulled high on the ZS-042 module: 0x57)")

# ---- 6. set the time
if SET_TIME:
    y, mo, d, h, mi, s, wd = SET_TIME
    w = reg_write(RTC, 0x00, [to_bcd(s), to_bcd(mi), to_bcd(h), wd, to_bcd(d), to_bcd(mo) | (0x80 if y >= 2100 else 0), to_bcd(y % 100)])
    st = reg_read(RTC, 0x0F, 1)
    w2 = reg_write(RTC, 0x0F, [st[0] & 0x7F]) if st else False     # clear OSF
    chk = reg_read(RTC, 0x00, 7)
    print("time set:               %s   now %s   %s" % ("acked" if w and w2 else "NOT ACKED", clock(chk)[1] if chk else "READ FAILED", "ok" if chk and clock(chk)[0] - (h * 3600 + mi * 60 + s) in (0, 1) else "WRONG"))
    ok &= w and w2 and chk is not None
chip.stop(ENG_A)
print("PASS" if ok else "FAIL")
