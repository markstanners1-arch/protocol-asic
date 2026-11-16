"""UART over RS-485, chip to chip (10 Nov 2026): engine A transmits, engine B receives, through two XY-485
auto-direction adapters and a twisted pair. Every byte is checked against what was sent.

    Two adapters: engine pin 0 (Mojo hole 41) -> adapter 1 TXD;  adapter 1 A+/B- -> pair -> adapter 2 A+/B-;
    adapter 2 RXD -> engine pin 3 (Mojo hole 32; a pull-up pin: the adapter's RXD high is weak, 2.58 V, and the
    pull-down input at Mojo hole 57 dragged it to 0.18 V);  both adapters' VCC on 3.3 V, GND common; adapter 2's TXD tied to
    its VCC (idle high: it only listens).
    One adapter (10 Nov, the first test): engine pin 0 -> TXD; A+ -> 1 k -> engine pin 15, read directly (high = 1);
    B- and RXD open; VCC from the Pico's 3V3 OUT (pin 36, not 3V3_EN at 37), GND common. Tests the adapter's driver and
    its automatic direction switch (it drives the 0s and lets the bias resistors pull the line back for the 1s).
For each rate, all 256 byte values in bursts of four (the RX FIFO is four deep), then the framing flag must be set on
every byte (bit 8). Rates: 9600, 115200, 250000 (DMX512), 500000 and 1000000 baud; the highest rate with every byte
right is reported. Needs the Mojo serialiser build (two engines); CHIP_HZ 40 MHz by default.
Settings before the file runs: CHIP_HZ, TX_PIN (0), RX_PIN (3), RATES, MODE ('loop', or 'hold': engine A holds its pin
high, then low, HOLD_S seconds each, for checking the adapters' LEDs and the A/B levels with a meter).
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script rs485_loop.py -Seconds 40 -Pre "CHIP_HZ=40_000_000"
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX
from programs import PROGRAMS

try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
try:
    TX_PIN
except NameError:
    TX_PIN = 0
try:
    RX_PIN
except NameError:
    RX_PIN = 3
try:
    RATES
except NameError:
    RATES = (9600, 115200, 250000, 500000, 1000000)
try:
    MODE
except NameError:
    MODE = "loop"
try:
    HOLD_S
except NameError:
    HOLD_S = 8

chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)


def clkdiv_for(baud):
    return round(CHIP_HZ / (8.0 * baud)) - 1


def setup_rx(baud):
    words, wb, wt = PROGRAMS["uart_rx"]
    chip.stop(ENG_B)
    chip.load_program(ENG_B, words)
    chip.write(ENG_B, R_CLKDIV, clkdiv_for(baud))
    chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_B, R_OUTCFG, 0)
    chip.write(ENG_B, R_MISC, 1 << 12)                       # in_right: LSB first
    chip.write(ENG_B, R_INCFG, RX_PIN | (RX_PIN << 5))       # in_base = jmp_pin = the RX pin
    chip.drain(ENG_B)
    chip.start(ENG_B)


def setup_tx(baud):
    words, wb, wt = PROGRAMS["uart_tx"]
    chip.stop(ENG_A)
    chip.load_program(ENG_A, words)
    chip.write(ENG_A, R_CLKDIV, clkdiv_for(baud))
    chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_A, R_OUTCFG, TX_PIN | (1 << 5) | (TX_PIN << 10))
    chip.write(ENG_A, R_MISC, 1 | (TX_PIN << 3) | (1 << 8) | (1 << 10) | (1 << 11))
    chip.write(ENG_A, R_INCFG, 0)
    chip.start(ENG_A)


def collect(n, ms):
    got = []
    t0 = time.ticks_ms()
    while len(got) < n and time.ticks_diff(time.ticks_ms(), t0) < ms:
        if chip.rx_level(ENG_B):
            got.append(chip.read(ENG_B, R_RX))
    return got


print("\n==== UART over RS-485: engine A pin %d -> adapter -> pair -> adapter -> engine B pin %d ====" % (TX_PIN, RX_PIN))
print("  chip ID 0x%04X" % chip.chip_id())

if MODE == "check":
    # engine A drives the TX pin high, low, high, low; engine B (programs/read_pins.asm, in_base = RX_PIN) reads it
    pw, wb, wt = PROGRAMS["read_pins"]
    chip.stop(ENG_B)
    chip.load_program(ENG_B, pw)
    chip.write(ENG_B, R_CLKDIV, 0); chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_B, R_OUTCFG, 0); chip.write(ENG_B, R_MISC, 0); chip.write(ENG_B, R_INCFG, RX_PIN)
    bad = 0
    for v in (1, 0, 1, 0):
        chip.stop(ENG_A)
        chip.load_program(ENG_A, [0xC081, 0xC000 | v, 0x0002])
        chip.write(ENG_A, R_CLKDIV, 0); chip.write(ENG_A, R_WRAP, wrap_reg(0, 0, 2))
        chip.write(ENG_A, R_OUTCFG, TX_PIN << 10); chip.write(ENG_A, R_MISC, 1); chip.write(ENG_A, R_INCFG, 0)
        chip.start(ENG_A)
        chip.stop(ENG_B); chip.start(ENG_B); time.sleep_ms(20)
        for _ in range(5):
            chip.read(ENG_B, R_RX)
        pins = chip.read(ENG_B, R_RX)
        got = pins & 1
        bad += 0 if got == v else 1
        print("  engine pin %d held %d -> engine pin %d reads %d  %s" % (TX_PIN, v, RX_PIN, got, "ok" if got == v else "WRONG"))
    chip.stop(ENG_A); chip.stop(ENG_B)
    print("\n==== %s ====" % ("PASS: the level arrives" if bad == 0 else "FAIL: %d of 4 wrong" % bad))
    raise SystemExit

if MODE == "hold":
    chip.stop(ENG_A)
    try:
        LEVEL                                   # one level only, left held after the script ends (meter at leisure)
        chip.write(ENG_A, R_OUTCFG, TX_PIN << 10)
        chip.write(ENG_A, R_MISC, 1)
        chip.write(ENG_A, R_WRAP, wrap_reg(0, 0, 2))
        chip.load_program(ENG_A, [0xC081, 0xC000 | (LEVEL & 1), 0x0002])
        chip.start(ENG_A)
        print("  engine pin %d held %s (until the next run)" % (TX_PIN, "HIGH" if LEVEL else "LOW"))
        raise SystemExit
    except NameError:
        pass
    for level, what in ((1, "HIGH (idle: A+ above B-, adapter 1 TXD LED off)"), (0, "LOW (adapter 1 drives the line: A+ below B-)")):
        chip.stop(ENG_A)
        chip.write(ENG_A, R_OUTCFG, TX_PIN << 10)                # set_base = the TX pin
        chip.write(ENG_A, R_MISC, 1)                             # set_count 1
        chip.write(ENG_A, R_WRAP, wrap_reg(0, 0, 2))
        chip.load_program(ENG_A, [0xC081, 0xC000 | level, 0x0002])   # set pindirs, 1 ; set pins, level ; jmp 2
        chip.start(ENG_A)
        print("  engine pin %d held %s for %d s" % (TX_PIN, what, HOLD_S))
        time.sleep(HOLD_S)
    chip.stop(ENG_A)
    print("\n==== hold done ====")
    raise SystemExit

ok_all, best = True, 0
for baud in RATES:
    setup_rx(baud)
    setup_tx(baud)
    time.sleep_ms(5)
    chip.drain(ENG_B)
    sent = list(range(256))
    got = []
    for i in range(0, 256, 4):
        for b in sent[i:i + 4]:
            chip.write(ENG_A, R_TX, b)
        got += collect(4, 200)
    want = [0x100 | b for b in sent]
    good = got == want
    actual = CHIP_HZ / (8.0 * (clkdiv_for(baud) + 1))
    if good:
        best = baud
        print("  %7d baud (clkdiv %3d, %.2f %% off): all 256 values exact  ok" % (baud, clkdiv_for(baud), 100 * (actual / baud - 1)))
    else:
        ok_all = False
        bad = [i for i in range(min(len(got), 256)) if got[i] != want[i]]
        print("  %7d baud (clkdiv %3d): WRONG: %d back of 256, %d differ, first at %s"
              % (baud, clkdiv_for(baud), len(got), len(bad) + max(0, 256 - len(got)), bad[:5]))
        for i in bad[:3]:
            print("      byte %d: sent %02X, got %04X%s" % (i, sent[i], got[i], "" if got[i] & 0x100 else " (framing error)"))
chip.stop(ENG_A)
chip.stop(ENG_B)
print("  highest rate with every byte right: %d baud" % best)
print("\n==== %s ====" % ("PASS" if ok_all else ("PASS up to %d baud" % best if best else "FAIL")))
