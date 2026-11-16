"""AT24C I2C EEPROM from the Pico: engine A runs programs/i2c_master.asm (SCL = engine pin 2 = J4-10, SDA = engine pin 3 = J4-13, 100 kHz).
A real device, not one of our own slaves. The test, in order:
  1. probe 0x50-0x57 (the AT24C's address range; its A0-A2 pins pick which) and 0x68 (a DS1307 clock if the module has one)
  2. read 8 bytes of the EEPROM as found (kept, and written back at the end: the test leaves it as it found it)
  3. write 8 new bytes in one page write, from a pattern seeded by the clock so old contents cannot pass
  4. wait out the write cycle by ACK polling (the chip does not answer while it stores: typically 3-5 ms) and print its length
  5. read the 8 bytes back in one sequential read; read one byte back with a random read
  6. put the original 8 bytes back and check
Set ADDR_BYTES before running if it is not an AT24C32/64 (2 address bytes); an AT24C01-16 uses 1. Both can be overridden by defining them first."""
import time
from chip_host import Chip, wrap_reg, ENG_A, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

try: ADDR_BYTES
except NameError: ADDR_BYTES = 2          # 2 for AT24C32 and larger (the DS1307 module's), 1 for AT24C01-AT24C16
try: MEM
except NameError: MEM = 0x0010           # page aligned for 8, 16 and 32 byte pages
CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
N = 8

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


def mem_addr(mem):
    ok = True
    if ADDR_BYTES == 2:
        ok &= send(mem >> 8)
    return ok & send(mem & 255)


def write_page(dev, mem, data):
    start(); ok = send(dev << 1) and mem_addr(mem)
    for d in data:
        ok = ok and send(d)
    stop()
    return ok


def wait_write(dev):
    """ACK polling: a busy EEPROM does not answer its address. Returns the milliseconds until it does (None if it never does)."""
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


print("==== AT24C from the Pico: engine A I2C master, SCL engine pin %d (J4-10), SDA pin %d (J4-13), 100 kHz, %d address byte(s) ====" % (SCL, SDA, ADDR_BYTES))
found = [a for a in list(range(0x50, 0x58)) + [0x68] if probe(a)]
print("answered:", ["0x%02X" % a for a in found] or "nothing")
eeprom = [a for a in found if 0x50 <= a <= 0x57]
if not eeprom:
    print("FAIL: nothing answered at 0x50-0x57: check SCL/SDA (J4-10/13), the pull-ups, and the module's power")
    raise SystemExit
dev = eeprom[0]
if len(eeprom) > 1:
    print("note: several addresses answered; using 0x%02X" % dev)
if dev == 0x50:
    print("note: the UNO or ESP32 test slave also answers at 0x50: unplug it from J4-10/13 before trusting this test")

ok = True
before = read_seq(dev, MEM, N)
print("as found at 0x%04X:     %s" % (MEM, " ".join("%02X" % b for b in before) if before else "READ FAILED"))
ok &= before is not None
seed = time.ticks_ms() & 0xFF
pattern = [((i * 37) + seed) & 0xFF for i in range(N)]
if pattern == before:
    pattern = [(b ^ 0xFF) for b in pattern]
w = write_page(dev, MEM, pattern)
cycle = wait_write(dev)
print("wrote  (seed %02X):       %s   page write %s, write cycle %s" % (seed, " ".join("%02X" % b for b in pattern), "acked" if w else "NOT ACKED", ("%d ms" % cycle) if cycle is not None else "never finished"))
ok &= w and cycle is not None
after = read_seq(dev, MEM, N)
print("sequential read back:   %s   %s" % (" ".join("%02X" % b for b in after) if after else "READ FAILED", "ok" if after == pattern else "WRONG"))
ok &= after == pattern
start(); r1 = send(dev << 1) and mem_addr(MEM + 3)
start(); r1 = r1 and send(dev << 1 | 1); b3 = recv(False); stop()
print("random read at +3:      %02X   %s (wanted %02X)" % (b3, "ok" if b3 == pattern[3] else "WRONG", pattern[3]))
ok &= r1 and b3 == pattern[3]
w = write_page(dev, MEM, before) if before else False
cycle2 = wait_write(dev)
restored = read_seq(dev, MEM, N)
print("original put back:      %s   %s" % (" ".join("%02X" % b for b in restored) if restored else "READ FAILED", "ok" if restored == before else "WRONG"))
ok &= restored == before and cycle2 is not None

if ADDR_BYTES == 2:
    # the high address byte: write at the top of a 32 KB part and check the low area did not change (no aliasing)
    HIGH = 0x7FF0
    hb = read_seq(dev, HIGH, N)
    pat2 = pattern[::-1]
    if pat2 == hb:
        pat2 = [b ^ 0xFF for b in pat2]
    w2 = write_page(dev, HIGH, pat2); c3 = wait_write(dev)
    top = read_seq(dev, HIGH, N)
    low = read_seq(dev, MEM, N)
    print("top of memory 0x%04X:   %s   %s (wrote %s)" % (HIGH, " ".join("%02X" % b for b in top) if top else "READ FAILED", "ok" if top == pat2 else "WRONG", " ".join("%02X" % b for b in pat2)))
    print("low area unchanged:     %s   %s" % (" ".join("%02X" % b for b in low) if low else "READ FAILED", "ok" if low == before else "WRONG: the high address byte is being ignored"))
    ok &= w2 and c3 is not None and top == pat2 and low == before
    write_page(dev, HIGH, hb); wait_write(dev)
    back = read_seq(dev, HIGH, N)
    print("top put back:           %s   %s" % (" ".join("%02X" % b for b in back) if back else "READ FAILED", "ok" if back == hb else "WRONG"))
    ok &= back == hb
chip.stop(ENG_A)
print("PASS" if ok else "FAIL")
