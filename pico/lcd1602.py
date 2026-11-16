"""LCD 1602 (HD44780) in 4-bit mode, from the Pico: engine B runs programs/lcd1602.asm on engine pins 8-13 (Mojo shield,
right header; the shield's LED2-LED7 light with them):
  D4 = pin 8, hole 132 (outer)   D5 = pin 9, hole 131 (inner)   D6 = pin 10, hole 127 (outer)
  D7 = pin 11, hole 126 (inner)  RS = pin 12, hole 124 (outer)  E = pin 13, hole 123 (inner)
The display: 1 VSS -> GND, 2 VDD -> 5 V, 3 V0 -> contrast (10 k pot between 5 V and GND, wiper to V0; or about 1 k to
GND), 5 R/W -> GND (write only: the display never drives its 5 V data lines back), 7-10 D0-D3 not connected,
15 A -> 5 V through 220 R (backlight), 16 K -> GND. 5 V from the breadboard power module, its GND joined to the Mojo's.
Program checked against a modelled HD44780 (model/test_lcd.py). The display cannot be read back, so the check is by eye:
the script prints each screen as it sends it; read the display back line by line against it.
  1. power-on sequence, two lines, display on, clear
  2. screen 1: "PROTOCOL EMU" / "chip ID 0xNNNN" (the ID read from the chip)
  3. screen 2: a count 0-9 at the end of line 1, one a second, line 2 "count:" (clear and home not used: DDRAM address)
  4. screen 3: every printable character 0x20-0x3F across both lines (punctuation and digits in order)
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script lcd1602.py -Seconds 40 -Pre "CHIP_HZ=40_000_000"
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_TX, R_FILTER
from programs import PROGRAMS, LABELS

try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
P = 8
ENG = ENG_B

chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)
print("\n==== LCD 1602 (HD44780, 4-bit): engine B, engine pins 8-13 ====")
cid = chip.chip_id()
print("  chip ID 0x%04X" % cid)
L = LABELS["lcd1602"]
words, wb, wt = PROGRAMS["lcd1602"]
chip.stop(ENG_A)
chip.stop(ENG)
chip.write(ENG, R_FILTER, 0)
chip.load_program(ENG, words)
chip.write(ENG, R_CLKDIV, round(CHIP_HZ * 1e-6) - 1)                     # one tick = 1 us
chip.write(ENG, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG, R_OUTCFG, P | (4 << 5) | (P << 10))                       # out_base = set_base = 8, out_count 4
chip.write(ENG, R_MISC, 5 | ((P + 5) << 3) | (1 << 8) | (1 << 10))        # set_count 5, E side-set on 13 (opt), MSB first
chip.drain(ENG)
chip.start(ENG)
time.sleep_ms(50)                                                         # the display's 40 ms after power-up


def send(word, wait_ms=0):
    chip.write(ENG, R_TX, word)
    if wait_ms:
        time.sleep_ms(wait_ms)


def nib(n):
    send(L["nib"] << 11 | n << 7, 6)                                     # the engine waits 5.2 ms after each


def cmd(b, long=False):
    send(L["cmd"] << 11 | b << 3 | int(long) << 2, 6 if long else 1)


def text(s):
    for c in s:
        send(L["data"] << 11 | ord(c) << 3, 1)


def at(line, col=0):
    cmd(0x80 | (0x40 if line else 0) | col)


def screen(l1, l2, hold_s):
    cmd(0x01, long=True)
    at(0); text(l1)
    at(1); text(l2)
    print("  screen: |%-16s|" % l1)
    print("          |%-16s|   read it back; next in %d s" % (l2, hold_s))
    time.sleep(hold_s)


for n in (3, 3, 3, 2):
    nib(n)
cmd(0x28); cmd(0x0C); cmd(0x06); cmd(0x01, long=True)
print("  1. initialised: 4-bit, two lines, display on, cleared")
print("  2.")
screen("PROTOCOL EMU", "chip ID 0x%04X" % cid, 8)
print("  3. count 0-9, one a second, at the end of line 1")
screen("count:", "", 0)
for i in range(10):
    at(0, 15); text(str(i))
    time.sleep(1)
print("  4.")
screen("".join(chr(c) for c in range(0x20, 0x30)), "".join(chr(c) for c in range(0x30, 0x40)), 8)
print("\n==== done: the result is your read-back (screens 2-4 and the count) ====")
