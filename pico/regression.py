"""Whole-chip regression from the Pico: the ESP32 sketch's 'r' (esp32/chip_test runAll) and 'x' (isolation) ported.
Set CHIP_HZ for the board: 12e6 the MachXO3L kit (two engines), 50e6 the Mojo v3 / Cyclone (three engines, ID 0x0023);
ENGINES for a build with another count (the Mojo "ser" build: 2, ID 0x0022).

Wiring, besides the host port of chip_host.py (CS GP17, SCK GP18, MOSI GP19, MISO GP16, IRQ GP20, GND):
    engine pin 0  -> Pico GP1 (board pin 2, UART0 RX): engine A's (and C's) UART out
    engine pin 15 <- Pico GP2 (board pin 4): test pulses and levels from the Pico (PIO, 0.1 us steps)
What it checks, every line against an expected value:
    the ID register (spec 2, engine count = ENGINES)
    at 115200, 57600 and 19200 baud: engine A sends a line through its uart_tx on pin 0, the Pico's UART reads it,
      engine B (measure_baud on pin 0) times A's bit, the IRQ pin rises with B's result and falls when it is read
    engine B (read_pins) sees pin 15 low and high as the Pico holds it
    glitch filter: engine B (measure_pulse) times 2 us and 20 us low pulses on pin 15, filter off then on (hold ~5 us):
      both seen with the filter off, only the 20 us one with it on
    isolation: A hung on a WAIT, B pushing 7, 8, 9, C sending "C!" over the UART meanwhile, then A reloaded alone
PASS only if every line is ok.
"""
import time
import rp2
from machine import Pin, UART
from chip_host import (Chip, wrap_reg, ENG_A, ENG_B, ENG_C, R_CTRL, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG,
                       R_TX, R_RX, R_STATUS, R_FILTER)
from programs import PROGRAMS

# CHIP_HZ and ENGINES may be set before this file runs (pico/run.ps1 -Pre "CHIP_HZ=40_000_000; ENGINES=2")
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 50_000_000
try:
    ENGINES
except NameError:
    ENGINES = 3 if CHIP_HZ >= 50e6 else 2
SPI_HZ = 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000      # under clk/8 either way
CHIP_MHZ = CHIP_HZ / 1e6
FILTER_P = 4 if CHIP_HZ >= 32e6 else 2                       # hold = 16 x 2^P clocks: 5.1 us at 50 MHz, 6.4 us at 40
FILTER_ON = (FILTER_P << 4) | 0xF
FILTER_HOLD_US = 16.0 * (1 << FILTER_P) / CHIP_MHZ
PULSE_PIN = 15                                               # engine pin wired to GP2
UART_RX_GP, PULSE_GP = 1, 2

chip = Chip(CHIP_HZ, SPI_HZ)
irq = Pin(20, Pin.IN)
errors = 0


def check(what, got, want):
    global errors
    ok = got == want
    if not ok:
        errors += 1
    print("  %-46s %8d  %s" % (what, got, "ok" if ok else "WRONG"))
    if not ok:
        print("  %-46s %8d" % ("   expected", want))


def setup(eng, name, clkdiv, outcfg, misc, incfg):
    words, wb, wt = PROGRAMS[name]
    chip.load_program(eng, words)
    chip.write(eng, R_CLKDIV, clkdiv)
    chip.write(eng, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(eng, R_OUTCFG, outcfg)
    chip.write(eng, R_MISC, misc)
    chip.write(eng, R_INCFG, incfg)


UART_TX_OUTCFG = 0 | (1 << 5) | (0 << 10)                                 # out_base 0, out_count 1, set_base 0
UART_TX_MISC = 1 | (0 << 3) | (1 << 8) | (1 << 10) | (1 << 11)           # set_count 1, side 0, 1 bit, opt, out_right


def stop_all():
    for e in range(ENGINES):
        chip.stop(e)


def run_at(baud):
    clkdiv = round(CHIP_HZ / (8.0 * baud)) - 1
    actual = CHIP_HZ / (8.0 * (clkdiv + 1))
    print("\n-- %d baud: engine A clock divider %d -> %.0f baud (%.2f %% off)" % (baud, clkdiv, actual, 100.0 * (actual - baud) / baud))
    stop_all()
    setup(ENG_B, "measure_baud", 0, 0, 1 << 12, 0)                        # in_right, in_base 0
    chip.start(ENG_B)
    setup(ENG_A, "uart_tx", clkdiv, UART_TX_OUTCFG, UART_TX_MISC, 0)
    check("A clock divider read back", chip.read(ENG_A, R_CLKDIV), clkdiv)
    chip.start(ENG_A)
    check("A running (STATUS bit 8)", (chip.read(ENG_A, R_STATUS) >> 8) & 1, 1)

    u = UART(0, baudrate=baud, tx=Pin(0), rx=Pin(UART_RX_GP), bits=8, parity=None, stop=1, rxbuf=256)
    time.sleep_ms(20)
    u.read()
    msg = "UHello from the chip!"
    for ch in msg:
        t0 = time.ticks_ms()
        while (chip.read(ENG_A, R_STATUS) & 7) >= 4 and time.ticks_diff(time.ticks_ms(), t0) < 200:
            pass
        chip.write(ENG_A, R_TX, ord(ch))
    time.sleep_ms(20 + len(msg) * 12000 // baud)
    got = u.read() or b""
    same = got == msg.encode()
    global errors
    if not same:
        errors += 1
    print('  %-46s "%s"  %s' % ("Pico received from the chip's pin 0", got.decode("ascii", "replace"), "ok" if same else "WRONG"))

    check("IRQ pin (engine B has a result)", irq.value(), 1)
    check("B RX FIFO level", chip.rx_level(ENG_B), 1)
    want = 8 * (clkdiv + 1)
    measured = chip.read(ENG_B, R_RX)
    check("B measured A's bit time (chip clocks)", measured, want)
    if measured:
        print("  %-46s %8.0f baud" % ("   = engine B's estimate of the baud rate", CHIP_HZ / measured))
    check("IRQ pin after reading", irq.value(), 0)


@rp2.asm_pio(set_init=rp2.PIO.OUT_HIGH)
def low_pulse():
    pull(block)
    mov(x, osr)
    set(pins, 0)
    label("hold")
    jmp(x_dec, "hold")
    set(pins, 1)                    # low for x + 2 cycles


def pin_diag():
    print("\n-- pin check: engine B reads the raw level of engine pin %d while the Pico holds GP%d" % (PULSE_PIN, PULSE_GP))
    p = Pin(PULSE_GP, Pin.OUT, value=1)
    stop_all()
    chip.write(ENG_A, R_FILTER, 0)
    setup(ENG_B, "read_pins", 0, 0, 0, PULSE_PIN)
    chip.start(ENG_B)
    global errors
    for lvl in (0, 1):
        p.value(lvl)
        time.sleep_ms(5)
        v = 0
        for _ in range(8):                          # past the four stale FIFO entries; keep the last
            v = chip.read(ENG_B, R_RX)
        ok = (v & 1) == lvl
        if not ok:
            errors += 1
        print("  GP%d held %s -> chip sees pins %d..: 0x%04X (that pin = %d)  %s" % (PULSE_GP, "HIGH" if lvl else "LOW ", PULSE_PIN, v, v & 1, "ok" if ok else "WRONG"))
    p.value(1)
    chip.stop(ENG_B)


def filter_test():
    print("\n-- glitch filter: engine B times low pulses on engine pin %d (from the Pico's PIO)" % PULSE_PIN)
    stop_all()
    setup(ENG_B, "measure_pulse", 0, 0, 0, PULSE_PIN)
    sm = rp2.StateMachine(0, low_pulse, freq=10_000_000, set_base=Pin(PULSE_GP))
    sm.active(1)
    time.sleep_ms(5)
    global errors
    for on in (0, 1):
        chip.write(ENG_A, R_FILTER, FILTER_ON if on else 0)
        if on:
            print("  filter on: N=15 P=%d, hold %.1f us" % (FILTER_P, FILTER_HOLD_US))
        check("FILTER read back (%s)" % ("on" if on else "off"), chip.read(ENG_B, R_FILTER), FILTER_ON if on else 0)
        chip.stop(ENG_B); chip.start(ENG_B)
        time.sleep_ms(2)
        for us in (2, 20):
            chip.drain(ENG_B)
            sm.put(us * 10 - 2)                     # 10 MHz: x + 2 cycles low
            time.sleep_ms(2)
            lvl = chip.rx_level(ENG_B)
            clocks = chip.read(ENG_B, R_RX) if lvl else 0
            seen = "it, %d clocks = %.1f us" % (clocks, clocks / CHIP_MHZ) if lvl else "nothing"
            expect_seen = not (on and us == 2)
            ok = (lvl == 1 and abs(clocks / CHIP_MHZ - us) < 1.5 + 0.1 * us) if expect_seen else (lvl == 0)
            if not ok:
                errors += 1
            print("  filter %-3s %2d us pulse: engine B saw %s   %s" % ("on" if on else "off", us, seen, "ok" if ok else "WRONG"))
    sm.active(0)
    chip.write(ENG_A, R_FILTER, 0)
    Pin(PULSE_GP, Pin.OUT, value=1)


def isolation_test():
    n = chip.chip_id() & 15
    print("\n-- isolation: A hung, the other %d working, A recovered alone" % (n - 1))
    p = Pin(PULSE_GP, Pin.OUT, value=0)                       # A's WAIT on this pin is never met
    for e in range(n):
        chip.stop(e)
    chip.write(ENG_A, R_FILTER, 0)
    setup(ENG_A, "measure_pulse", 0, 0, 0, PULSE_PIN)
    setup(ENG_B, "push_789", 0, 0, 0, 0)
    if n >= 3:
        setup(ENG_C, "uart_tx", round(CHIP_HZ / (8.0 * 115200)) - 1, UART_TX_OUTCFG, UART_TX_MISC, 0)
        u = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(UART_RX_GP), bits=8, parity=None, stop=1, rxbuf=256)
    chip.start(ENG_A); time.sleep_ms(2)
    check("A hung on its first WAIT (STATUS pc 0, running)", (chip.read(ENG_A, R_STATUS) >> 8) & 63, 1)
    chip.start(ENG_B); time.sleep_ms(2)
    check("B works while A hangs (word 1)", chip.read(ENG_B, R_RX), 7)
    check("B works while A hangs (word 2)", chip.read(ENG_B, R_RX), 8)
    global errors
    if n >= 3:
        chip.start(ENG_C); time.sleep_ms(2)
        u.read()
        chip.write(ENG_C, R_TX, ord("C")); chip.write(ENG_C, R_TX, ord("!"))
        time.sleep_ms(20)
        got = u.read() or b""
        ok = got == b"C!"
        if not ok:
            errors += 1
        print("  %-46s [%s]  %s" % ("C sent over UART while A hangs", got.decode("ascii", "replace"), "ok" if ok else "WRONG"))
    check("A still hung (pc 0, running)", (chip.read(ENG_A, R_STATUS) >> 8) & 63, 1)
    chip.stop(ENG_A)
    words, wb, wt = PROGRAMS["push_789"]
    chip.load_program(ENG_A, words)
    chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt)); chip.write(ENG_A, R_INCFG, 0)
    chip.start(ENG_A); time.sleep_ms(2)
    check("A recovered: pushes 7", chip.read(ENG_A, R_RX), 7)
    check("B still running", (chip.read(ENG_B, R_STATUS) >> 8) & 1, 1)
    check("B's word 3 intact", chip.read(ENG_B, R_RX), 9)
    if n >= 3:
        check("C still running", (chip.read(ENG_C, R_STATUS) >> 8) & 1, 1)
    for e in range(n):
        chip.stop(e)
    p.value(1)


Pin(PULSE_GP, Pin.OUT, value=1)
cid = chip.chip_id()
print("\n==== Whole chip regression from the Pico at %.0f MHz: ID 0x%04X ====" % (CHIP_MHZ, cid))
check("ID register", cid, 0x0020 | ENGINES)
check("ID: host port spec version 2", (cid >> 4) & 15, 2)
check("ID: engines", cid & 15, ENGINES)
stop_all()
for e in range(ENGINES):
    chip.drain(e)
run_at(115200)
run_at(57600)
run_at(19200)
pin_diag()
filter_test()
isolation_test()
print("\n==== %s (%d problems) ====" % ("FAIL" if errors else "PASS", errors))
