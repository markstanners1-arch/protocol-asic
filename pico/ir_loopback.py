"""IR loopback from the Pico, the port of the ESP32 sketch's 't' command. Engine A runs programs/ir_tx.asm and flashes the IR emitter on
engine pin 9 (J4-19 / H14); engine B runs programs/ir_nec.asm on the receiver (engine pin 1, J4-8). Six frames are sent, B's two words
for each are read back and compared with what was sent. The emitter must face the receiver a few cm apart, phones away."""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CTRL, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_STATUS
from programs import PROGRAMS

CHIP_HZ = 12_000_000
chip = Chip(CHIP_HZ)
print("ID", "0x%04X" % chip.chip_id())


def setup(eng, name, clkdiv, outcfg, misc, incfg):
    words, wb, wt = PROGRAMS[name]
    chip.stop(eng)
    chip.load_program(eng, words)
    chip.write(eng, R_CLKDIV, clkdiv)
    chip.write(eng, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(eng, R_OUTCFG, outcfg)
    chip.write(eng, R_MISC, misc)
    chip.write(eng, R_INCFG, incfg)
    chip.drain(eng)


div_a = round(CHIP_HZ / (3 * 38400)) - 1                      # a third of a 38.4 kHz carrier cycle
div_b = round(CHIP_HZ * 50e-6) - 1                            # the decoder's 50 us tick
setup(ENG_A, "ir_tx", div_a, 9 << 10, 1 | (1 << 11), 0)       # set_base 9, set_count 1, out_right
setup(ENG_B, "ir_nec", div_b, 0, 1 << 12, 1 | (1 << 5))       # in_right; in_base 1, jmp_pin 1
chip.start(ENG_B)
chip.start(ENG_A)
print("==== IR loopback from the Pico: emitter engine pin 9 (clkdiv %d, %.1f kHz) to receiver engine pin 1 ====" % (div_a, CHIP_HZ / (3 * (div_a + 1)) / 1000))

frames = [("address 00 command 45", 0xFF00, 0xBA45),
          ("address 04 command 08 (LG power)", 0xFB04, 0xF708),
          ("address 5A command 3C", 0xA55A, 0xC33C),
          ("all ones", 0xFFFF, 0xFFFF),
          ("all zeros", 0x0000, 0x0000),
          ("raw 2916 5CB7 (the Manhattan's button 1)", 0x2916, 0x5CB7)]
passed = 0
for name, w1, w2 in frames:
    chip.write(ENG_A, R_TX, w1)
    chip.write(ENG_A, R_TX, w2)
    time.sleep_ms(130)                                        # the longest frame is 86 ms
    tx_level = chip.read(ENG_A, R_STATUS) & 0x0F
    rx = chip.rx_level(ENG_B)
    g1 = chip.read(ENG_B, R_RX) if rx >= 1 else 0
    g2 = chip.read(ENG_B, R_RX) if rx >= 2 else 0
    ok = rx == 2 and g1 == w1 and g2 == w2
    passed += ok
    print("  %-42s sent %04X %04X  got %s  %s" % (name, w1, w2, ("%04X %04X" % (g1, g2)) if rx else "nothing", "ok" if ok else
          "WRONG (A's TX FIFO holds %d: %s)" % (tx_level, "A has not sent it" if tx_level else "A sent it")))
    time.sleep_ms(30)
chip.stop(ENG_A)
chip.stop(ENG_B)
print("==== IR loopback %s: %d of %d frames came back exactly ====" % ("PASS" if passed == len(frames) else "FAIL", passed, len(frames)))
