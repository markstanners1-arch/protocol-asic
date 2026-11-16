"""DALI from the Pico (the two programs are checked against the model, model/test_dali.py; not yet run on hardware). Engine A runs programs/dali_tx.asm on
engine pin 8 (J4-18, out only) into the DALI interface's TX input; engine B runs programs/dali_rx.asm on engine pin 0 (J4-6) from
the interface's RX output. Interface: the Waveshare Pico-DALI2 shield (kit 3.3 V to its pin 36, GND to a GND
pin, J4-18 to its pin 9, its pin 5 to J4-6, a DALI PSU or 12-18 V through 56 ohm on its bus terminal, the gear across the bus).
J4-6 normally carries the Pico's GP0 UART lead (pico/uart_rx.py): move that lead out first.
The scripted sequence, each line printed with the frame sent and the word that came back:
    broadcast DAPC 254        no answer expected (0x000)
    QUERY ACTUAL LEVEL        254
    broadcast DAPC 127        no answer
    QUERY ACTUAL LEVEL        127
    QUERY DEVICE TYPE         6 (LED module)
    QUERY STATUS              a frame with bit 2 (lamp on) set; the other bits are printed by name
    OFF                       no answer
    QUERY ACTUAL LEVEL        0
PASS only if every answer matches. Words back from B: 0x100 | byte = a frame, 0x000 = no answer, 0x200 | part = framing error
(the bits read before a missing mid-bit edge). Set CHIP_HZ for the board (12 MHz kit, 50 MHz Cyclone).
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_STATUS
from programs import PROGRAMS, LABELS

CHIP_HZ = 12_000_000
TX_PIN, RX_PIN = 8, 0
WINDOW = 96                                   # ticks of a bit/8 = 10 ms: the standard's answer comes within 9.2 ms
DIV = round(CHIP_HZ / 9600) - 1               # a tick of 104.17 us, an eighth of a 1200 bit/s bit (1249 at 12 MHz, 5207 at 50)
chip = Chip(CHIP_HZ)
ok = True


def setup(eng, name, outcfg, misc, incfg):
    words, wb, wt = PROGRAMS[name]
    chip.stop(eng)
    chip.load_program(eng, words)
    chip.write(eng, R_CLKDIV, DIV)
    chip.write(eng, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(eng, R_OUTCFG, outcfg)
    chip.write(eng, R_MISC, misc)
    chip.write(eng, R_INCFG, incfg)
    chip.drain(eng)
    chip.start(eng)


def exchange(word, ms=80):
    """Arm B with the window, push the frame to A, wait for B's one word (None if it never comes: a wiring fault)."""
    chip.drain(ENG_B)
    chip.write(ENG_B, R_TX, WINDOW)
    chip.write(ENG_A, R_TX, word)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        if chip.rx_level(ENG_B):
            return chip.read(ENG_B, R_RX)
    return None


def describe(w):
    if w is None: return "NOTHING (B never answered: is it running, is J4-6 wired?)"
    if w & 0x100: return "answer %02X (%d)" % (w & 0xFF, w & 0xFF)
    if w & 0x200: return "FRAMING ERROR, bits so far %s" % bin(w & 0xFF)
    return "no answer"


STATUS_BITS = ("gear failure", "lamp failure", "lamp on", "limit error", "fade running", "reset state", "no short address", "power failure")


def step(name, word, want=None, lamp_on=None):
    """want: the byte expected (None = no answer expected); lamp_on: for QUERY STATUS, expect a frame with bit 2 at this value."""
    global ok
    got = exchange(word)
    if lamp_on is not None:
        good = got is not None and (got & 0x100) and bool(got & 0x04) == lamp_on
        extra = "  [%s]" % ", ".join(b for i, b in enumerate(STATUS_BITS) if got & (1 << i)) if got and got & 0x100 else ""
    else:
        good = got == (0x000 if want is None else 0x100 | want)
        extra = ""
    ok = ok and good
    print("  %-34s sent %04X  %-44s %s%s" % (name, word, describe(got), "ok" if good else "WRONG (expected %s)" % ("no answer" if want is None else want), extra))
    time.sleep_ms(20)                         # the standard's 9.2 ms before another forward frame, with room


print("chip ID %04X; DALI tick clkdiv %d" % (chip.chip_id(), DIV))
setup(ENG_A, "dali_tx", TX_PIN | (1 << 5) | (TX_PIN << 10), 1, 0)                     # out_base, out_count 1, set_base; set_count 1; MSB first
setup(ENG_B, "dali_rx", 0, 0, RX_PIN | (RX_PIN << 5) | (LABELS["dali_rx"]["fault"] << 10))   # in_base, jmp_pin, fault_addr; MSB first
print("==== DALI: engine A sends on pin 8 (J4-18), engine B listens on pin 0 (J4-6) ====")
step("broadcast DAPC 254", 0xFEFE)
step("QUERY ACTUAL LEVEL", 0xFFA0, 254)
step("broadcast DAPC 127", 0xFE7F)
step("QUERY ACTUAL LEVEL", 0xFFA0, 127)
step("QUERY DEVICE TYPE", 0xFF99, 6)
step("QUERY STATUS", 0xFF90, lamp_on=True)
step("OFF", 0xFF00)
step("QUERY ACTUAL LEVEL", 0xFFA0, 0)
chip.stop(ENG_A)
chip.stop(ENG_B)
print("==== DALI %s ====" % ("PASS" if ok else "FAIL"))
