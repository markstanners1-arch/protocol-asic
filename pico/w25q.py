"""W25Q32 SPI flash from the Pico: engine A runs programs/spi_master.asm (mode 0, MSB first) to a real SPI slave, a Winbond
W25Q32 module (32 Mbit = 4 MB, 3.3 V). Not run yet: the module arrives 5 Nov 2026.

Pins. spi_master.asm takes its four pins as ONE group from set_base: SCK = base + 0 (side-set), MOSI = base + 1 (out),
MISO = base + 2 (in), CS = base + 3 (set), and it drives SCK, MOSI and CS itself ("set pindirs, 11"), so the group must be four
consecutive engine pins with base + 2 able to read. On the kit that is engine pins 4-7 only: pins 8-13 are output only (a MISO
there reads nothing), pins 15-19 are input only and pin 14 is not on the header, and 0-3 carry the serial line, the IR receiver and
the I2C bus. So the flash goes where the 74HC595 went (wiring sheet section 11): the keypad's four COLUMN leads come out of
J4-14 to 17 first (one at a time, as the 595 already is); the rows and their pull-ups can stay.
    J4-14 (L16) engine pin 4 = SCK  -> module CLK        J4-15 (K14) engine pin 5 = MOSI -> module DI (IO0)
    J4-16 (K16) engine pin 6 = MISO <- module DO (IO1)   J4-17 (K15) engine pin 7 = CS   -> module CS
    module VCC -> J4-1 or J4-2 (3.3 V, never 5 V), module GND -> the negative rail (wired to J4-11 or 12).
    WP (IO2) and HOLD (IO3): most modules pull them up on the board; if yours brings them out bare, tie both to 3.3 V.
SCK = 12 MHz / (6 * (CLKDIV + 1)) = 1 MHz with CLKDIV 1. One 16-bit command word per byte: xfer << 11 | byte << 3, and the byte
that came back on MISO is pushed to the RX FIFO; select / deselect words drop and raise CS.

The test, in order, each line with its expected readback:
  1. JEDEC ID (0x9F): EF 40 16 = Winbond, SPI type 0x40, 2^0x16 = 4 MB. Other IDs are decoded too (the table below).
  2. the 64-bit unique ID (0x4B, four dummy bytes): any eight bytes but not all 00 or all FF, and the same on a second read.
  3. status register 1 (0x05): BUSY 0, WEL 0; block-protect bits BP0-2 should be 0 (if not, page program is silently refused).
  4. 16 bytes at address 0 read as found (0x03): a new module reads FF FF ... (erased); whatever it is, it is not changed.
  5. a non-destructive proof of writing: starting at the top of the memory and stepping down 16 bytes at a time through the top 4 KB
     sector, the first 16-byte region that reads all FF is page-programmed (0x06 write enable, WEL must read 1, then 0x02) with
     a pattern seeded by the clock, BUSY is polled (expect about 0.3-3 ms), and the region is read back: must equal the pattern.
     Flash can only clear bits (FF -> anything), never set them, so each run uses up one more 16-byte region; bringing them
     back to FF takes a 4 KB sector erase (0x20, about 50-400 ms), which wears the part (100,000 cycles rated), so it runs only
     with ERASE = True, after which the whole top sector must read FF again.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script w25q.py -Seconds 30        (set ERASE = True first for the erase)"""
import time
from chip_host import Chip, wrap_reg, ENG_A, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

try: ERASE
except NameError: ERASE = False        # True: erase the top 4 KB sector at the end (wears the part: only when the FF regions run out)
CHIP_HZ = 12_000_000
BASE = 4                               # engine pins 4 SCK, 5 MOSI, 6 MISO, 7 CS = J4-14, 15, 16, 17
CLKDIV = 1                             # SCK = CHIP_HZ / (6 * (CLKDIV + 1)) = 1 MHz
N = 16

MAKERS = {0xEF: "Winbond", 0xC2: "Macronix", 0x20: "Micron/ST or XMC", 0xC8: "GigaDevice", 0x1C: "EON", 0xBF: "SST/Microchip",
          0x01: "Spansion/Cypress/Infineon", 0x9D: "ISSI", 0x0B: "XTX", 0x68: "Boya", 0x1F: "Adesto/Atmel", 0xA1: "Fudan", 0x85: "Puya"}
WINBOND_TYPES = {0x40: "W25Q..JV/FV, 3 V SPI", 0x60: "W25Q..JW, 1.8 V part (not for this 3.3 V bench)", 0x70: "W25Q..JV-IM, DTR", 0x30: "W25X"}

chip = Chip(CHIP_HZ)
L = LABELS["spi_master"]
words, wb, wt = PROGRAMS["spi_master"]
chip.stop(ENG_A)
chip.write(ENG_A, R_FILTER, 0)
chip.load_program(ENG_A, words)
chip.write(ENG_A, R_CLKDIV, CLKDIV)
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, (BASE + 1) | (1 << 5) | (BASE << 10))        # out = MOSI (1 pin), set_base = SCK (4 pins)
chip.write(ENG_A, R_MISC, 4 | (BASE << 3) | (1 << 8) | (1 << 10))         # set_count 4, side-set = SCK, 1 bit, optional
chip.write(ENG_A, R_INCFG, BASE + 2)                                      # in = MISO
chip.drain(ENG_A)
chip.start(ENG_A)
time.sleep_ms(5)


def xfer(b):
    """One byte out on MOSI; returns the byte that came back on MISO."""
    chip.write(ENG_A, R_TX, L["xfer"] << 11 | (b & 0xFF) << 3)
    t = time.ticks_ms()
    while chip.rx_level(ENG_A) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine A: is the kit loaded?")
    return chip.read(ENG_A, R_RX) & 0xFF


def select():
    chip.write(ENG_A, R_TX, L["select"] << 11); time.sleep_us(50)


def deselect():
    chip.write(ENG_A, R_TX, L["deselect"] << 11); time.sleep_us(50)


def command(cmd, addr=None, dummy=0, n=0, data=()):
    """CS low; the command byte, an optional 24-bit address, dummy bytes, data bytes out; then n bytes read; CS high."""
    select()
    xfer(cmd)
    if addr is not None:
        xfer(addr >> 16); xfer(addr >> 8); xfer(addr)
    for _ in range(dummy):
        xfer(0)
    for d in data:
        xfer(d)
    out = [xfer(0xFF) for _ in range(n)]
    deselect()
    return out


def status1():
    return command(0x05, n=1)[0]


def read(addr, n):
    return command(0x03, addr, n=n)


def wait_busy(limit_ms):
    """Polls BUSY (status bit 0); returns the milliseconds it took, or None if it never cleared."""
    t = time.ticks_ms()
    while status1() & 1:
        if time.ticks_diff(time.ticks_ms(), t) > limit_ms:
            return None
    return time.ticks_diff(time.ticks_ms(), t)


def hexs(bs):
    return " ".join("%02X" % b for b in bs)


ok = True
print("==== W25Q32 SPI flash from the Pico: engine A SPI master, SCK pin %d (J4-14), MOSI pin %d (J4-15), MISO pin %d (J4-16), CS pin %d (J4-17), SCK %.2f MHz ====" % (BASE, BASE + 1, BASE + 2, BASE + 3, CHIP_HZ / (6 * (CLKDIV + 1)) / 1e6))

# ---- 1. JEDEC ID
jid = command(0x9F, n=3)
maker, mtype, cap = jid
print("JEDEC ID (0x9F):        %s   (expect EF 40 16 for a W25Q32)" % hexs(jid))
if jid in ([0, 0, 0], [0xFF, 0xFF, 0xFF]):
    print("FAIL: no device: all %s means MISO reads a stuck level. Check CS and CLK leads (J4-17, J4-14), DO to J4-16, and the module's 3.3 V and ground." % ("00" if maker == 0 else "FF"))
    chip.stop(ENG_A)
    raise SystemExit
size = (1 << cap) if 0x10 <= cap <= 0x19 else 0
print("  manufacturer 0x%02X = %s; type 0x%02X%s; capacity byte 0x%02X = %s" % (
    maker, MAKERS.get(maker, "unknown maker"), mtype,
    (" (" + WINBOND_TYPES.get(mtype, "unknown Winbond type") + ")") if maker == 0xEF else "",
    cap, ("2^%d = %d MB = %d Mbit" % (cap, size >> 20, size >> 17)) if size else "not a power-of-two capacity code"))
print("  (0x15 would be a W25Q16, 2 MB; 0x17 a W25Q64, 8 MB; 0x18 a W25Q128, 16 MB; C2 20 16 a Macronix MX25L3233, C8 40 16 a GigaDevice GD25Q32)")
ok &= jid == [0xEF, 0x40, 0x16]
if jid != [0xEF, 0x40, 0x16]:
    print("  note: not the expected EF 40 16; the rest of the test runs on the capacity it reports")
if not size:
    size = 4 << 20

# ---- 2. unique ID
uid = command(0x4B, dummy=4, n=8)
uid2 = command(0x4B, dummy=4, n=8)
u_ok = uid == uid2 and uid not in ([0] * 8, [0xFF] * 8)
print("unique ID (0x4B):       %s   %s" % (hexs(uid), "ok (read twice, same both times)" if u_ok else "WRONG (second read %s)" % hexs(uid2)))
ok &= u_ok

# ---- 3. status register 1
s1 = status1()
bp = (s1 >> 2) & 7
print("status 1 (0x05):        %02X   BUSY %d, WEL %d, BP2:0 %d, TB %d, SEC %d, SRP %d   %s" % (
    s1, s1 & 1, (s1 >> 1) & 1, bp, (s1 >> 5) & 1, (s1 >> 6) & 1, (s1 >> 7) & 1,
    "ok" if (s1 & 3) == 0 and bp == 0 else "WRONG: expect BUSY 0, WEL 0 and no block protection" + (" (BP bits set: the write test will be refused)" if bp else "")))
ok &= (s1 & 3) == 0 and bp == 0

# ---- 4. 16 bytes at address 0, as found
first = read(0, N)
print("bytes at 0x000000:      %s   (a new module reads all FF; left as found)" % hexs(first))

# ---- 5. the write proof in the top sector
sector = size - 4096
region = None
for a in range(size - N, sector - 1, -N):
    if read(a, N) == [0xFF] * N:
        region = a
        break
if region is None:
    print("write proof:            no 16-byte region in the top sector 0x%06X-0x%06X reads FF: set ERASE = True to clear it, then run again" % (sector, size - 1))
    ok = False
else:
    seed = time.ticks_ms() & 0xFF
    pattern = [((i * 37) + seed) & 0xFF for i in range(N)]
    command(0x06)                                                      # write enable
    wel = (status1() >> 1) & 1
    print("write enable (0x06):    WEL %d   %s" % (wel, "ok" if wel else "WRONG: WEL did not set (WP low, or the command did not arrive)"))
    ok &= wel == 1
    command(0x02, region, data=pattern)                                # page program (16 bytes inside one 256-byte page)
    took = wait_busy(20)
    back = read(region, N)
    print("page program (0x02) at 0x%06X (seed %02X): %s" % (region, seed, "busy for %d ms (expect under 3)" % took if took is not None else "BUSY never cleared"))
    print("read back (0x03):       %s   %s" % (hexs(back), "ok" if back == pattern else "WRONG (wrote %s)" % hexs(pattern)))
    ok &= took is not None and back == pattern
    wel2 = (status1() >> 1) & 1
    print("WEL after programming:  %d   %s" % (wel2, "ok (the part clears it itself)" if wel2 == 0 else "WRONG"))
    ok &= wel2 == 0
    left = (region - sector) // N
    print("  %d FF regions left in the top sector below this one; the region just written stays written until a sector erase" % left)

if ERASE:
    command(0x06)
    command(0x20, sector)                                              # 4 KB sector erase
    took = wait_busy(1000)
    clean = all(read(a, 256) == [0xFF] * 256 for a in range(sector, size, 256))
    print("sector erase (0x20) of 0x%06X: %s; whole sector reads FF: %s" % (sector, "took %d ms (expect 50-400)" % took if took is not None else "BUSY never cleared", "ok" if clean else "WRONG"))
    ok &= took is not None and clean
else:
    print("  (ERASE is False: the top sector was not erased)")
same = read(0, N)
print("bytes at 0x000000 again: %s   %s" % (hexs(same), "unchanged" if same == first else "CHANGED: WRONG"))
ok &= same == first
chip.stop(ENG_A)
print("PASS" if ok else "FAIL")
