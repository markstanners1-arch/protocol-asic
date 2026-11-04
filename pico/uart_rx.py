"""UART receive on the chip, from the Pico (4 Nov 2026). Engine B runs programs/uart_rx.asm on engine pin 0 (J4-6).
Two tests, both scripted so every byte is checked against what was sent:
  1. loopback: engine A runs uart_tx on the same pin 0 and the Pico pushes bytes to A; B must hand back every byte,
     at 9600, 19200, 57600 and 115200 baud (no wiring: the byte goes out of the pad and back in)
  2. pico: the Pico's own UART0 TX (GP0, board pin 1) wired to J4-6 sends to the chip with engine A stopped: a text
     line and all 256 byte values in bursts of four at 115200 (the RX FIFO is four deep), then a 256-byte stream at
     9600 read as it comes, then a burst at the wrong baud rate to show the framing-error flag (bit 8 clear).
Set MODE below, or run both. PASS only if every byte came back exactly.
"""
import time
from machine import UART, Pin
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_STATUS
from programs import PROGRAMS

MODE = "both"                 # "loop", "pico" or "both"
CHIP_HZ = 12_000_000
RX_PIN = 0
chip = Chip(CHIP_HZ)
ok = True


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
    chip.write(ENG_A, R_OUTCFG, RX_PIN | (1 << 5) | (RX_PIN << 10))         # out_base, out_count 1, set_base
    chip.write(ENG_A, R_MISC, 1 | (RX_PIN << 3) | (1 << 8) | (1 << 10) | (1 << 11))   # set_count 1, side_base, side_count 1, side_opt, out_right
    chip.write(ENG_A, R_INCFG, 0)
    chip.start(ENG_A)


def collect(n, ms):
    """Read up to n words from B within ms."""
    got = []
    t0 = time.ticks_ms()
    while len(got) < n and time.ticks_diff(time.ticks_ms(), t0) < ms:
        if chip.rx_level(ENG_B):
            got.append(chip.read(ENG_B, R_RX))
    return got


def report(name, sent, got):
    global ok
    want = [0x100 | b for b in sent]
    good = got == want
    ok = ok and good
    if good:
        print("  %-52s %d bytes exact  ok" % (name, len(sent)))
    else:
        bad = [i for i in range(min(len(got), len(want))) if got[i] != want[i]]
        print("  %-52s WRONG: %d sent, %d back, first differences at %s" % (name, len(sent), len(got), bad[:6]))
        for i in bad[:4]:
            print("      byte %d: sent %02X, got %04X%s" % (i, sent[i], got[i], "" if got[i] & 0x100 else " (framing error flag)"))


def loopback():
    print("==== 1. loopback: engine A transmits on pin 0, engine B receives on pin 0 ====")
    for baud in (9600, 19200, 57600, 115200):
        setup_rx(baud)
        setup_tx(baud)
        msg = [(i * 73 + 5) & 0xFF for i in range(32)] + list(b"Hi Mark")
        got = []
        for i in range(0, len(msg), 4):                       # bursts of four: the FIFOs are four deep
            for b in msg[i:i + 4]:
                chip.write(ENG_A, R_TX, b)
            got += collect(min(4, len(msg) - i), 200)
        report("%6d baud, clkdiv %3d, 39 bytes" % (baud, clkdiv_for(baud)), msg, got)
    chip.stop(ENG_A)


def from_pico():
    print("==== 2. the Pico's UART0 TX (GP0) to J4-6, engine A stopped ====")
    chip.stop(ENG_A)
    chip.write(ENG_A, R_OUTCFG, 0)                            # A releases pin 0 (its direction bit is cleared by the stop)
    setup_rx(115200)
    u = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1), bits=8, parity=None, stop=1)
    time.sleep_ms(20)
    chip.drain(ENG_B)
    text = list(b"The chip hears the Pico.")
    got = []
    for i in range(0, len(text), 4):
        u.write(bytes(text[i:i + 4])); got += collect(min(4, len(text) - i), 200)
    report("115200: a text line in bursts of 4", text, got)
    print("      received: %s" % bytes(w & 0xFF for w in got))
    allv = list(range(256))
    got = []
    for i in range(0, 256, 4):
        u.write(bytes(allv[i:i + 4])); got += collect(4, 200)
    report("115200: all 256 values in bursts of 4", allv, got)

    setup_rx(9600)
    u = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), bits=8, parity=None, stop=1)
    time.sleep_ms(20)
    chip.drain(ENG_B)
    stream = [(i * 37 + 11) & 0xFF for i in range(256)]
    u.write(bytes(stream))                                    # 267 ms of continuous bytes; read as they come
    got = collect(256, 1500)
    report("9600: a 256-byte stream, no gaps", stream, got)

    u = UART(0, baudrate=4800, tx=Pin(0), rx=Pin(1), bits=8, parity=None, stop=1)   # wrong rate on purpose
    time.sleep_ms(20)
    chip.drain(ENG_B)
    u.write(bytes([0x55, 0x55, 0x55, 0x55])); got = collect(8, 300)
    flagged = sum(1 for w in got if not (w & 0x100))
    print("  4800 baud into a 9600 receiver: %d words back, %d with the framing-error flag  (expected: flags)" % (len(got), flagged))
    chip.stop(ENG_B)


print("chip ID %04X" % chip.chip_id())
if MODE in ("loop", "both"):
    loopback()
if MODE in ("pico", "both"):
    from_pico()
chip.stop(ENG_A); chip.stop(ENG_B)
print("PASS" if ok else "FAIL")
