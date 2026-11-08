"""Lead check for the loopback jumper TD+ (engine pin 1, Mojo hole 34) -> engine pin 19 (hole 74): engine A holds TD+ high,
then low (set pindirs / set pins), engine B reads pins 15-19 (programs/read_pins.asm, in_base 15) each time.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script jumper_check.py -Seconds 15 -Pre "CHIP_HZ=40_000_000" """
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_RX
from programs import PROGRAMS
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
chip = Chip(CHIP_HZ, 4_000_000)
print("\n==== jumper check: TD+ (hole 34) -> engine pin 19 (hole 74) ====")
bad = 0
pw, wb, wt = PROGRAMS["read_pins"]
chip.stop(ENG_B)
chip.load_program(ENG_B, pw)
chip.write(ENG_B, R_CLKDIV, 0); chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_B, R_OUTCFG, 0); chip.write(ENG_B, R_MISC, 0); chip.write(ENG_B, R_INCFG, 15)
chip.write(ENG_A, 0x2B, 0)                       # serialiser off: the program's levels on the pins
for v in (1, 0, 1, 0):
    chip.stop(ENG_A)
    chip.load_program(ENG_A, [0xC081, 0xC000 | v, 0x0002])   # set pindirs, 1 (TD+); set pins, v; jmp 2
    chip.write(ENG_A, R_CLKDIV, 0); chip.write(ENG_A, R_WRAP, wrap_reg(0, 0, 2))
    chip.write(ENG_A, R_OUTCFG, 1 | (1 << 5) | (1 << 10)); chip.write(ENG_A, R_MISC, 1); chip.write(ENG_A, R_INCFG, 0)
    chip.start(ENG_A)
    chip.stop(ENG_B); chip.start(ENG_B); time.sleep_ms(5)
    for _ in range(5):
        chip.read(ENG_B, R_RX)                   # older words out (read_pins keeps pushing)
    pins = chip.read(ENG_B, R_RX)
    p19 = (pins >> 4) & 1
    ok = p19 == v
    bad += 0 if ok else 1
    print("  TD+ held %d -> engine pin 19 reads %d  (pins 15-19 = %s)  %s" % (v, p19, bin(pins & 31), "ok" if ok else "WRONG"))
chip.stop(ENG_A); chip.stop(ENG_B)
print("\n==== %s ====" % ("PASS: the jumper connects TD+ to pin 19" if bad == 0 else "FAIL: %d of 4 wrong" % bad))
