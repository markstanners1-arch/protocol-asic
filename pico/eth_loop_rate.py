"""Bit errors at the pin, measured by the chip's own receiver: engine A sends the same short frame at 10 Mbit/s REPEAT
times in full duplex, its receiver catches each one from a jumper TD+ (engine pin 1, Mojo hole 34) -> engine pin 19
(hole 74), and every frame is compared word for word. The RJ45 lead may stay connected: this tells whether the frames
leave the chip's pin correct, apart from the cable and the network card.
Needs the Mojo build with receive and full duplex (build.sh ser clk40). Settings: REPEAT (default 500).
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script eth_loop_rate.py -Seconds 60 -Pre "CHIP_HZ=40_000_000"
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG
from programs import PROGRAMS

R_TX, R_SERCFG, R_SERDIV, R_SERSTAT = 0x26, 0x2B, 0x2C, 0x33
R_CRCPOLY_LO, R_CRCPOLY_HI, R_CRCINIT_LO, R_CRCINIT_HI = 0x2D, 0x2E, 0x2F, 0x30
R_RXCFG, R_RXGAP, R_RXSTAT, R_RXDATA = 0x34, 0x35, 0x36, 0x37
TDP, RXPIN, KEY, FDX, SERCFG = 1, 19, 0xA000, 0x0100, 0x027F
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
try:
    REPEAT
except NameError:
    REPEAT = 500


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
print("\n==== bit errors at the pin: %d frames at 10 Mbit/s, TD+ (hole 34) -> pin 19 (hole 74) ====" % REPEAT)
print("  chip ID 0x%04X" % chip.chip_id())
pw, wb, wt = PROGRAMS["eth_tx"]
chip.stop(ENG_A)
chip.stop(ENG_B)
chip.load_program(ENG_A, pw)
chip.write(ENG_A, R_CLKDIV, 0)
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, TDP | (2 << 5) | (TDP << 10))
chip.write(ENG_A, R_MISC, 2 | (1 << 11) | (1 << 12))
chip.write(ENG_A, R_INCFG, 0)
chip.write(ENG_A, R_SERCFG, SERCFG)
chip.write(ENG_A, R_SERDIV, 1)
chip.write(ENG_A, R_CRCPOLY_LO, 0x8320); chip.write(ENG_A, R_CRCPOLY_HI, 0xEDB8)
chip.write(ENG_A, R_CRCINIT_LO, 0xFFFF); chip.write(ENG_A, R_CRCINIT_HI, 0xFFFF)
chip.write(ENG_A, R_RXGAP, 6)
chip.start(ENG_A)
time.sleep_ms(2)
chip.write(ENG_A, R_SERCFG, SERCFG | KEY | FDX)
mode_ok = ((chip.read(ENG_A, R_SERCFG) >> 7) & 7) == 0b110
print("  full duplex with the hardware preamble in force: %s" % ("ok" if mode_ok else "WRONG"))

data = bytes((0xFF,) * 6 + (0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x88, 0xB5)) + bytes(range(0x30, 0x30 + 14))
want = words_of(data + crc32(data).to_bytes(4, "little"))
burst = bytearray(2 + 2 * (1 + len(data) // 2))
c = Chip.cmd(False, ENG_A, R_TX)
burst[0], burst[1] = c >> 8, c & 255
for i, w in enumerate([len(data) // 2] + words_of(data)):
    burst[2 + 2 * i], burst[3 + 2 * i] = w >> 8, w & 255

good, nothing, bad_bits, first_bad = 0, 0, 0, None
for n in range(REPEAT):
    chip.write(ENG_A, R_RXCFG, RXPIN | 0x40 | 0x80)              # pin 19, both clock edges, arm
    chip.cs(0); time.sleep_us(2); chip.spi.write(burst); time.sleep_us(2); chip.cs(1)
    time.sleep_ms(2)
    st = chip.read(ENG_A, R_RXSTAT)
    if not st & 1:
        nothing += 1
        continue
    got = [chip.read(ENG_A, R_RXDATA) for _ in range(len(want))]
    if got == want:
        good += 1
    else:
        bad_bits += sum(bin(a ^ b).count("1") for a, b in zip(got, want))
        if first_bad is None:
            first_bad = got
print("  frames received word for word: %d of %d; no frame seen: %d; wrong bits in the others: %d"
      % (good, REPEAT, nothing, bad_bits))
if first_bad is not None:
    print("  first wrong: " + " ".join("%04x" % w for w in first_bad))
    print("  expected:    " + " ".join("%04x" % w for w in want))
chip.write(ENG_A, R_SERCFG, SERCFG | KEY)
chip.stop(ENG_A)
print("\n==== %s ====" % ("PASS" if good == REPEAT and mode_ok else "FAIL"))
