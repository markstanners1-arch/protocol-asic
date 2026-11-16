"""NEC remote decoder from the Pico, the port of the ESP32 sketch's 'm' command. Engine B runs programs/ir_nec.asm on the receiver
(engine pin 1, J4-8) and every frame is printed as address and command with the inverse bytes checked, 'repeat n' while a button is
held. Runs until Ctrl-C (pico/run.ps1 sends one when its time is up)."""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_RX, R_STATUS
from programs import PROGRAMS

CHIP_HZ = 12_000_000
chip = Chip(CHIP_HZ)
words, wb, wt = PROGRAMS["ir_nec"]
chip.stop(ENG_A); chip.stop(ENG_B)
chip.load_program(ENG_B, words)
div = round(CHIP_HZ * 50e-6) - 1
chip.write(ENG_B, R_CLKDIV, div)
chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_B, R_OUTCFG, 0)
chip.write(ENG_B, R_MISC, 1 << 12)                            # in_right: LSB first
chip.write(ENG_B, R_INCFG, 1 | (1 << 5))                      # in_base 1, jmp_pin 1
chip.drain(ENG_B)
chip.start(ENG_B)
print("==== NEC remote from the Pico: receiver on engine pin 1 (J4-8), tick 50 us (clkdiv %d); press buttons ====" % div)
t0 = time.ticks_ms()
repeats = 0
try:
    while True:
        if chip.rx_level(ENG_B) == 0:
            time.sleep_ms(2)
            continue
        w1 = chip.read(ENG_B, R_RX)
        t = time.ticks_diff(time.ticks_ms(), t0)
        if w1 == 0xFFFF:
            repeats += 1
            print("  t=%6d ms  repeat %d" % (t, repeats))
            continue
        repeats = 0
        tw = time.ticks_ms()
        while chip.rx_level(ENG_B) == 0 and time.ticks_diff(time.ticks_ms(), tw) < 60:   # the command pair follows within 36 ms
            time.sleep_ms(1)
        if chip.rx_level(ENG_B) == 0:
            print("  t=%6d ms  incomplete frame: %04X" % (t, w1))
            continue
        w2 = chip.read(ENG_B, R_RX)
        aok = (w1 >> 8) == (~w1 & 0xFF)
        cok = (w2 >> 8) == (~w2 & 0xFF)
        s = ("address %02X  " % (w1 & 0xFF)) if aok else ("address %04X (16-bit, no inverse)  " % w1)
        s += "command %02X" % (w2 & 0xFF)
        if not cok:
            s += "  BAD INVERSE (%04X)" % w2
        print("  t=%6d ms  %s" % (t, s))
except KeyboardInterrupt:
    pass
chip.stop(ENG_B)
print("==== NEC remote done ====")
