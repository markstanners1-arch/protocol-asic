"""4x4 keypad from the Pico, the port of the ESP32 sketch's 'y' command. Engine B runs programs/keypad.asm: columns = engine pins 4-7
(J4-14 to 17), rows = pins 16-19 (J4-27 to 30) with 10 k pull-ups. Every change of the 16-key map is printed with the keys named,
until Ctrl-C (pico/run.ps1 sends one when its time is up). Bit 4*(3-c)+r is the key at row r, column c."""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_RX
from programs import PROGRAMS

KEYS = ("123A", "456B", "789C", "*0#D")                       # [row][column], as printed on the keypad
CHIP_HZ = 12_000_000
chip = Chip(CHIP_HZ)
words, wb, wt = PROGRAMS["keypad"]
chip.stop(ENG_A); chip.stop(ENG_B)
chip.load_program(ENG_B, words)
chip.write(ENG_B, R_CLKDIV, round(CHIP_HZ * 20e-6) - 1)      # 20 us tick
chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_B, R_OUTCFG, 4 << 10)                          # set_base 4
chip.write(ENG_B, R_MISC, 4)                                  # set_count 4, MSB first in
chip.write(ENG_B, R_INCFG, 16)                                # in_base 16
chip.drain(ENG_B)
chip.start(ENG_B)
print("==== keypad from the Pico: press keys ====")
try:
    while True:
        if chip.rx_level(ENG_B) == 0:
            time.sleep_ms(2)
            continue
        m = chip.read(ENG_B, R_RX)
        names = "".join("[%s] " % KEYS[b % 4][3 - b // 4] for b in range(15, -1, -1) if m & (1 << b))
        print("  map %04X  %s" % (m, names if m else "(nothing pressed)"))
except KeyboardInterrupt:
    pass
chip.stop(ENG_B)
print("==== keypad done ====")
