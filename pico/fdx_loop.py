"""Full duplex on engine A, on real wires: a jumper from TD+ (engine pin 1, Mojo hole 34) to engine pin 19 (hole 74).
Engine A, in full duplex with the hardware preamble, sends a frame from its 16-word ring while its own receiver catches it
from pin 19 into the 48-word ring; the received words are read from RXDATA (0x37) and checked word for word.
  A. 10 Mbit/s (40 MHz, SERDIV 1): a short frame, 14 words + the CRC unit's FCS, so it fits the ring (no topping up)
  B. a full Ethernet frame (30 words + FCS) at 20 kbit/s: the host tops the ring up as the level allows
  C. the rules: a keyed mode change while B's frame goes out is refused; a write without the key changes nothing; idle
     again, the change back to transmit is taken
Needs the Mojo build with receive and full duplex (build.sh ser clk40 from the duplex branch). Prints PASS or FAIL.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script fdx_loop.py -Seconds 60 -Pre "CHIP_HZ=40_000_000"
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_STATUS
from programs import PROGRAMS

R_TX, R_SERCFG, R_SERDIV, R_SERSTAT = 0x26, 0x2B, 0x2C, 0x33
R_CRCPOLY_LO, R_CRCPOLY_HI, R_CRCINIT_LO, R_CRCINIT_HI = 0x2D, 0x2E, 0x2F, 0x30
R_RXCFG, R_RXGAP, R_RXSTAT, R_RXDATA = 0x34, 0x35, 0x36, 0x37
TDP, RXPIN = 1, 19
KEY = 0xA000                                     # 101 in SERCFG [15:13]
FDX = 0x0100                                     # SERCFG [8]
SERCFG = 0x027F                                  # enable, Manchester, differential, end marker, CRC append, complement,
                                                 # CRC watches SER, hardware preamble [9], skip 0
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000

errors = 0


def check(what, got, want, fmt="0x%04X"):
    global errors
    ok = got == want
    if not ok:
        errors += 1
    print("  %-60s %s  %s" % (what, fmt % got, "ok" if ok else "WRONG, expected " + fmt % want))


def crc32(data):
    c = 0xFFFFFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    return c ^ 0xFFFFFFFF


def words_of(b):
    return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]


chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)
print("\n==== full duplex on engine A, loopback TD+ (hole 34) -> engine pin 19 (hole 74) ====")
print("  chip ID 0x%04X" % chip.chip_id())
chip.stop(ENG_A)
chip.stop(ENG_B)
pw, wb, wt = PROGRAMS["eth_tx"]


def setup(serdiv):
    chip.stop(ENG_A)
    chip.load_program(ENG_A, pw)
    chip.write(ENG_A, R_CLKDIV, 0)
    chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_A, R_OUTCFG, TDP | (2 << 5) | (TDP << 10))
    chip.write(ENG_A, R_MISC, 2 | (1 << 11) | (1 << 12))        # set_count 2, out_right, in_right (LSB first both ways)
    chip.write(ENG_A, R_INCFG, 0)
    chip.write(ENG_A, R_SERCFG, SERCFG)
    chip.write(ENG_A, R_SERDIV, serdiv)
    chip.write(ENG_A, R_CRCPOLY_LO, 0x8320); chip.write(ENG_A, R_CRCPOLY_HI, 0xEDB8)
    chip.write(ENG_A, R_CRCINIT_LO, 0xFFFF); chip.write(ENG_A, R_CRCINIT_HI, 0xFFFF)
    chip.write(ENG_A, R_RXGAP, 3 * (serdiv + 1))                # 3/4 bit in half-clocks
    chip.start(ENG_A)
    time.sleep_ms(2)
    chip.write(ENG_A, R_SERCFG, SERCFG | KEY | FDX)              # keyed: full duplex (the engine must be running)
    check("SERCFG [9:7]: hardware preamble, full duplex in force", (chip.read(ENG_A, R_SERCFG) >> 7) & 7, 0b110, "%d")
    chip.write(ENG_A, R_RXCFG, RXPIN | 0x40 | 0x80)              # pin 19, both clock edges, arm
    check("RXSTAT: the receiver on, nothing yet", chip.read(ENG_A, R_RXSTAT), 0x8000)


def read_frame(n):
    return [chip.read(ENG_A, R_RXDATA) for _ in range(n)]


# ---- A. 10 Mbit/s, a frame that fits the ring
print("\n-- A. 10 Mbit/s (SERDIV 1), 14 words + FCS, all in the ring before it starts")
setup(1)
data = bytes((0xFF,) * 6 + (0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x88, 0xB5)) + bytes(range(0x30, 0x30 + 14))
want = words_of(data + crc32(data).to_bytes(4, "little"))
burst = bytearray(2 + 2 * (1 + len(data) // 2))
c = Chip.cmd(False, ENG_A, R_TX)
burst[0], burst[1] = c >> 8, c & 255
for i, w in enumerate([len(data) // 2] + words_of(data)):
    burst[2 + 2 * i], burst[3 + 2 * i] = w >> 8, w & 255
chip.cs(0); time.sleep_us(2); chip.spi.write(burst); time.sleep_us(2); chip.cs(1)
time.sleep_ms(5)
check("SERSTAT after the frame (level, busy, underrun)", chip.read(ENG_A, R_SERSTAT), 0)
st = chip.read(ENG_A, R_RXSTAT)
check("RXSTAT: receiver on, words, ready", st & 0xFF01, 0x8000 | (len(want) << 8) | 1)
got = read_frame(len(want))
check("received words equal the frame sent (destination to FCS)", int(got == want), 1, "%d")
if got != want:
    print("  got  " + " ".join("%04x" % w for w in got))
    print("  want " + " ".join("%04x" % w for w in want))

# ---- B and C. a full frame at 20 kbit/s, the host topping up the ring; the rules while it goes out
print("\n-- B. a full Ethernet frame (30 words + FCS) at 20 kbit/s (SERDIV 999), the host topping up the ring")
setup(999)
data = bytes((0xFF,) * 6 + (0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x88, 0xB5)) + bytes(range(0x30, 0x30 + 46))
want = words_of(data + crc32(data).to_bytes(4, "little"))
feed = [len(data) // 2] + words_of(data)
peak, tried = 0, False
t0 = time.ticks_ms()
while feed and time.ticks_diff(time.ticks_ms(), t0) < 3000:
    lvl = chip.read(ENG_A, R_SERSTAT) & 0x7F
    peak = max(peak, lvl)
    if lvl < 16:
        chip.write(ENG_A, R_TX, feed.pop(0))
    if not tried and len(feed) < 10:                              # C. mid-frame: a keyed change, and one without the key
        tried = True
        chip.write(ENG_A, R_SERCFG, SERCFG | KEY)                   # keyed: back to transmit, while sending
        st = chip.read(ENG_A, R_RXSTAT)
        check("C. keyed change while the frame goes out: refused flag", (st >> 3) & 1, 1, "%d")
        chip.write(ENG_A, R_SERCFG, SERCFG | 0x0080)                # bit 7 without the key
        check("C. still full duplex after both", (chip.read(ENG_A, R_SERCFG) >> 7) & 3, 2, "%d")
t0 = time.ticks_ms()
while chip.read(ENG_A, R_STATUS) & 0x4000 and time.ticks_diff(time.ticks_ms(), t0) < 2000:
    time.sleep_ms(5)
time.sleep_ms(5)
check("transmit ring level never above 16", int(peak <= 16), 1, "%d")
check("all words fed, frame sent, no underrun (words left, STATUS [15:14])",
      "%d %d" % (len(feed), chip.read(ENG_A, R_STATUS) >> 14), "0 0", "%s")
st = chip.read(ENG_A, R_RXSTAT)
check("RXSTAT: receiver on, words, ready", st & 0xFF01, 0x8000 | (len(want) << 8) | 1)
got = read_frame(len(want))
check("received words equal the frame sent (destination to FCS)", int(got == want), 1, "%d")
if got != want:
    print("  got  " + " ".join("%04x" % w for w in got))
    print("  want " + " ".join("%04x" % w for w in want))
chip.write(ENG_A, R_SERCFG, SERCFG | KEY)                         # C. idle now: back to transmit
check("C. idle: the keyed change back to transmit is taken", (chip.read(ENG_A, R_SERCFG) >> 7) & 3, 0, "%d")
chip.stop(ENG_A)
print("\n==== %s (%d problems) ====" % ("FAIL" if errors else "PASS", errors))
