"""Live levels of engine pins 0-15 as the chip sees them (programs/read_pins.asm on engine B, in_base 0): 1 = high. Prints on every change
and once a second, for 20 s or until Ctrl-C. Handy for checking I2C (pins 2 = SCL, 3 = SDA: both must idle high through the pull-ups)."""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_RX
from programs import PROGRAMS

try: BASE
except NameError: BASE = 0
chip = Chip()
words, wb, wt = PROGRAMS["read_pins"]
chip.stop(ENG_A); chip.stop(ENG_B)
chip.load_program(ENG_B, words)
chip.write(ENG_B, R_CLKDIV, 0)
chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_B, R_OUTCFG, 0)
chip.write(ENG_B, R_MISC, 0)
chip.write(ENG_B, R_INCFG, BASE)
chip.drain(ENG_B)
chip.start(ENG_B)
print("==== pins %d..%d as the chip sees them (1 = high), 20 s ====" % (BASE, BASE + 15))
last = None
t0 = time.ticks_ms(); tl = 0
try:
    while time.ticks_diff(time.ticks_ms(), t0) < 20000:
        v = None
        for _ in range(8):
            v = chip.read(ENG_B, R_RX)
        if v != last or time.ticks_diff(time.ticks_ms(), tl) > 1000:
            print("  t=%5d ms  %s   (SCL pin 2 = %d, SDA pin 3 = %d)" % (time.ticks_diff(time.ticks_ms(), t0), "".join(str((v >> i) & 1) for i in range(16)), (v >> 2) & 1, (v >> 3) & 1))
            last = v; tl = time.ticks_ms()
        time.sleep_ms(50)
except KeyboardInterrupt:
    pass
chip.stop(ENG_B)
print("==== done ====")
