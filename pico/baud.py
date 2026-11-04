"""Baud-rate measurer from the Pico (4 Nov 2026): engine B runs programs/measure_baud.asm on engine pin 0 (J4-6, the Pico's
GP0 UART lead) at clkdiv 0, so its stopwatch counts chip clocks (12 MHz). The Pico sends one 'U' (0x55: its start bit is a
single bit-time low) at each rate; the engine reports the start bit's length in clocks and the host turns that into a
baud rate. Scripted: the rates below, each must come back within 2 % (one clock is 4 % of a bit at 460800, so that one
is allowed 5 %). PASS only if every rate is identified."""
import time
from machine import UART, Pin
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_RX
from programs import PROGRAMS

CHIP_HZ = 12_000_000
RATES = (1200, 2400, 9600, 19200, 38400, 57600, 115200, 230400, 460800)
chip = Chip(CHIP_HZ)
chip.stop(ENG_A)
words, wb, wt = PROGRAMS["measure_baud"]
ok = True
print("chip ID %04X" % chip.chip_id())
print("==== baud measurer: engine B times the start bit of a 'U' from the Pico's GP0 on J4-6, in 12 MHz clocks ====")
for rate in RATES:
    chip.stop(ENG_B)
    chip.load_program(ENG_B, words)
    chip.write(ENG_B, R_CLKDIV, 0)
    chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_B, R_OUTCFG, 0)
    chip.write(ENG_B, R_MISC, 0)
    chip.write(ENG_B, R_INCFG, 0)                       # in_base 0: pin 0
    chip.drain(ENG_B)
    u = UART(0, baudrate=rate, tx=Pin(0), rx=Pin(1), bits=8, parity=None, stop=1)
    time.sleep_ms(20)
    chip.start(ENG_B)
    time.sleep_ms(2)
    u.write(b"U")
    t = time.ticks_ms()
    while chip.rx_level(ENG_B) == 0 and time.ticks_diff(time.ticks_ms(), t) < 200:
        pass
    if chip.rx_level(ENG_B) == 0:
        print("  %7d baud: nothing measured" % rate); ok = False
        continue
    clocks = chip.read(ENG_B, R_RX)
    got = CHIP_HZ / clocks
    err = (got - rate) / rate * 100
    lim = 5 if rate >= 230400 else 2
    good = abs(err) <= lim
    ok = ok and good
    print("  %7d baud: start bit %5d clocks = %6.2f us  ->  %8.0f baud  (%+.2f %%)  %s" % (rate, clocks, clocks / 12.0, got, err, "ok" if good else "WRONG"))
chip.stop(ENG_B)
print("PASS" if ok else "FAIL")
