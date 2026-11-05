"""Frames from engine 0's serialiser (ISA v0.3) on the Mojo "ser" build, sent from the Pico, for the logic analyser or scope.
Settings may be set before the file runs:  pico/run.ps1 -Script eth_tx.py -Pre "MODE='dali'"
    MODE     'eth'  (default) a minimum Ethernet frame, programs/eth_tx.asm, Manchester, differential, end marker, FCS
                    appended (0xEDB88320 / 0xFFFFFFFF, complemented, skip 4 preamble words), LSB first; half-bit HALF_US
             'dali' one 16-bit word 0xFE51, programs/ser_tx.asm, Manchester, differential, end marker, no CRC, MSB first,
                    half-bit 416.67 us (DALI's 1200 bit/s)
             'full' the Ethernet frame at 10 Mbit/s: half-bit 50 ns, needs CHIP_HZ 40e6 (the clk40 build): SERDIV 1
             'leads' no frames: TD+ high / TD- low, then TD+ low / TD- high, then both low, HOLD_S (8) seconds each,
                    for checking the analyser leads
    CHIP_HZ  50_000_000 (default) or 40_000_000
    HALF_US  the eth half-bit in us (default 1.0: SERDIV 49 at 50 MHz, 500 kbit/s)
    FRAMES, PERIOD_MS   how many frames and how far apart (defaults per mode below)
Pins: TD+ = engine pin 1 (Mojo shield hole 34), TD- = engine pin 2 (hole 35); both low between frames.
Every frame: count and words pushed in one SPI burst; afterwards SERSTAT must read 0 (FIFO empty, not busy, no underrun)
and the chip's CRC register must equal the CRC of the bytes after the preamble (not complemented). Prints PASS or FAIL.
The bytes sent are printed as one hex line for docs/bench/decode_manchester.py --expect.
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CTRL, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_STATUS
from programs import PROGRAMS

R_TX = 0x26
R_SERCFG, R_SERDIV, R_CRCPOLY_LO, R_CRCPOLY_HI, R_CRCINIT_LO, R_CRCINIT_HI = 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30
R_CRC_LO, R_CRC_HI, R_SERSTAT = 0x31, 0x32, 0x33
TDP = 1                                         # TD+ = engine pin 1, TD- = engine pin 2

try:
    MODE
except NameError:
    MODE = "eth"
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 50_000_000
try:
    HALF_US
except NameError:
    HALF_US = 1.0
DEF = {"eth": (30, 100), "dali": (20, 200), "full": (3000, 10), "leads": (0, 0)}[MODE]
try:
    FRAMES
except NameError:
    FRAMES = DEF[0]
try:
    PERIOD_MS
except NameError:
    PERIOD_MS = DEF[1]

errors = 0


def check(what, got, want, fmt="0x%04X"):
    global errors
    ok = got == want
    if not ok:
        errors += 1
    print("  %-52s %s  %s" % (what, fmt % got, "ok" if ok else "WRONG, expected " + fmt % want))


def crc32(data):
    c = 0xFFFFFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    return c ^ 0xFFFFFFFF


chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)

if MODE == "leads":
    # analyser lead check: engine A holds TD+/TD- at fixed levels, HOLD_S seconds each (set pindirs, 3; set pins, v; jmp)
    try:
        HOLD_S
    except NameError:
        HOLD_S = 8
    print("\n==== lead check: engine A holds engine pins 1 (TD+, hole 34) and 2 (TD-, hole 35) ====")
    print("  chip ID 0x%04X" % chip.chip_id())
    chip.stop(ENG_A)
    chip.write(ENG_A, R_CLKDIV, 0)
    chip.write(ENG_A, R_WRAP, wrap_reg(0, 0, 2))
    chip.write(ENG_A, R_OUTCFG, TDP | (2 << 5) | (TDP << 10))
    chip.write(ENG_A, R_MISC, 2)
    chip.write(ENG_A, R_INCFG, 0)
    chip.write(ENG_A, R_SERCFG, 0)
    t0 = time.ticks_ms()
    for v, what in ((1, "TD+ HIGH, TD- LOW"), (2, "TD+ LOW,  TD- HIGH"), (0, "both LOW")):
        chip.stop(ENG_A)
        chip.load_program(ENG_A, [0xC083, 0xC000 | v, 0x0002])
        chip.start(ENG_A)
        print("  t = %5.1f s  step %d: %s for %d s" % (time.ticks_diff(time.ticks_ms(), t0) / 1000, (1, 2, 0).index(v) + 1,
                                                   what, HOLD_S))
        time.sleep(HOLD_S)
    chip.stop(ENG_A)
    print("\n==== PASS (lead check steps sent; read the analyser) ====")
    raise SystemExit

if MODE == "dali":
    prog, half_s, lsb = "ser_tx", 1 / 2400, False
    sercfg = 0x000F                             # enable, Manchester, differential, end marker
    data = bytes((0xFE, 0x51))
    words = [0xFE51]
    crc_words = 0
else:
    prog, lsb = "eth_tx", True
    half_s = 50e-9 if MODE == "full" else HALF_US * 1e-6
    sercfg = 0x107F                             # enable, Manchester, differential, end marker, CRC append, complement,
                                                # CRC watches SER, skip 4 words
    preamble = bytes([0x55] * 7 + [0xD5])
    header = bytes((0xFF,) * 6 + (0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x88, 0xB5))
    payload = bytes(range(0x30, 0x30 + 46))
    data = header + payload
    raw = preamble + data
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    crc_words = 2

serdiv = round(CHIP_HZ * half_s) - 1
half_clk = serdiv + 1
half_ns = half_clk * 1e9 / CHIP_HZ
nbits = 16 * len(words) + 32 * (crc_words // 2)
frame_us = (2 * nbits + 6) * half_ns / 1000
print("\n==== serialiser frames from the Pico: mode %s, chip %.0f MHz ====" % (MODE, CHIP_HZ / 1e6))
if MODE == "full" and abs(half_clk * 1e9 / CHIP_HZ - 50) > 0.5:
    print("  10 Mbit/s needs a whole number of clocks per 50 ns half-bit: not possible at %.0f MHz" % (CHIP_HZ / 1e6))
    print("\n==== FAIL (chip clock) ====")
    raise SystemExit
print("  SERDIV %d: half-bit %d clocks = %.3f us, bit %.3f us (%.1f bit/s), %s first" %
      (serdiv, half_clk, half_ns / 1000, 2 * half_ns / 1000, 1e9 / (2 * half_ns), "LSB" if lsb else "MSB"))
print("  frame: %d words = %d bits%s, then the end marker 6 half-bits = %.3f us; on the pair for %.1f us" %
      (len(words), nbits, " with the 32-bit FCS" if crc_words else "", 6 * half_ns / 1000, frame_us))
if MODE != "dali":
    fcs = crc32(data)
    print("  preamble 55 x 7 + d5; destination ff:ff:ff:ff:ff:ff, source 02:00:00:00:00:01, type 0x88b5, payload 30..5d")
    print("  FCS expected 0x%08X, on the wire (LSB first) %02x %02x %02x %02x" %
          (fcs, fcs & 255, (fcs >> 8) & 255, (fcs >> 16) & 255, fcs >> 24))
print("  sent (for --expect): " + "".join("%02x" % b for b in data))
print("  TD+ engine pin 1 (hole 34), TD- engine pin 2 (hole 35)")

cid = chip.chip_id()
print("  chip ID 0x%04X" % cid)
chip.stop(ENG_A)
chip.stop(ENG_B)
pw, wb, wt = PROGRAMS[prog]
chip.load_program(ENG_A, pw)
chip.write(ENG_A, R_CLKDIV, 0)
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
outcfg = TDP | (2 << 5) | (TDP << 10)           # out_base 1, out_count 2, set_base 1
misc = 2 | ((1 << 11) if lsb else 0)            # set_count 2, out_right for LSB first
chip.write(ENG_A, R_OUTCFG, outcfg)
chip.write(ENG_A, R_MISC, misc)
chip.write(ENG_A, R_INCFG, 0)
chip.write(ENG_A, R_SERCFG, sercfg)
chip.write(ENG_A, R_SERDIV, serdiv)
chip.write(ENG_A, R_CRCPOLY_LO, 0x8320); chip.write(ENG_A, R_CRCPOLY_HI, 0xEDB8)
chip.write(ENG_A, R_CRCINIT_LO, 0xFFFF); chip.write(ENG_A, R_CRCINIT_HI, 0xFFFF)
check("OUTCFG read back", chip.read(ENG_A, R_OUTCFG), outcfg)
check("MISC read back", chip.read(ENG_A, R_MISC), misc)
check("SERCFG read back (0 = no serialiser in this build)", chip.read(ENG_A, R_SERCFG), sercfg)
check("SERDIV read back", chip.read(ENG_A, R_SERDIV), serdiv, "%d")
check("CRCPOLY read back", (chip.read(ENG_A, R_CRCPOLY_HI) << 16) | chip.read(ENG_A, R_CRCPOLY_LO), 0xEDB88320, "0x%08X")
check("CRCINIT read back", (chip.read(ENG_A, R_CRCINIT_HI) << 16) | chip.read(ENG_A, R_CRCINIT_LO), 0xFFFFFFFF, "0x%08X")
chip.start(ENG_A)
time.sleep_ms(2)
check("engine A running, serialiser idle (STATUS [8], [14], [15])", chip.read(ENG_A, R_STATUS) & 0xC100, 0x0100)

burst = bytearray(2 + 2 * (1 + len(words)))
c = Chip.cmd(False, ENG_A, R_TX)
burst[0], burst[1] = c >> 8, c & 255
for i, w in enumerate([len(words)] + words):
    burst[2 + 2 * i], burst[3 + 2 * i] = w >> 8, w & 255

want_crc = (crc32(data) ^ 0xFFFFFFFF) if MODE != "dali" else None
print("  sending %d frames, one every %d ms" % (FRAMES, PERIOD_MS))
bad_stat, bad_crc, first = 0, 0, None
for n in range(FRAMES):
    t0 = time.ticks_ms()
    chip.cs(0); time.sleep_us(2)
    chip.spi.write(burst)
    time.sleep_us(2); chip.cs(1)
    time.sleep_us(int(frame_us) + 200)
    while chip.read(ENG_A, R_SERSTAT) & 0x100 and time.ticks_diff(time.ticks_ms(), t0) < PERIOD_MS + 100:
        pass
    st = chip.read(ENG_A, R_SERSTAT)
    crc = (chip.read(ENG_A, R_CRC_HI) << 16) | chip.read(ENG_A, R_CRC_LO)
    if first is None:
        first = (st, crc)
    if st != 0:
        bad_stat += 1
    if want_crc is not None and crc != want_crc:
        bad_crc += 1
    while time.ticks_diff(time.ticks_ms(), t0) < PERIOD_MS:
        pass
check("SERSTAT after frame 1 (FIFO level, busy, underrun)", first[0], 0)
check("frames with SERSTAT not 0", bad_stat, 0, "%d")
if want_crc is not None:
    check("chip CRC register after frame 1 (= FCS not complemented)", first[1], want_crc, "0x%08X")
    check("frames with a different CRC register", bad_crc, 0, "%d")
chip.stop(ENG_A)
print("\n==== %s (%d problems) ====" % ("FAIL" if errors else "PASS", errors))
