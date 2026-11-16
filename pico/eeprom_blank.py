"""Put a page of the AT24C256 back to blank (0xFF) from the Pico: engine A runs programs/i2c_master.asm on J4-10/13 as at24c.py
does. Set MEM (page aligned) and N below. Used 4 Nov 2026 to undo FD FD FD FD left at 0x0020 by runs made with a dead
logic analyser clamping the bus. Prints the page before and after; PASS when it reads all FF."""
import time
from chip_host import Chip, wrap_reg, ENG_A, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

MEM, N, DEV = 0x0020, 8, 0x50
CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
chip = Chip(CHIP_HZ)
L = LABELS["i2c_master"]
words, wb, wt = PROGRAMS["i2c_master"]
chip.stop(ENG_A)
chip.write(ENG_A, R_FILTER, 0)
chip.load_program(ENG_A, words)
chip.write(ENG_A, R_CLKDIV, round(CHIP_HZ / (10 * 100000)) - 1)
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, SDA | (1 << 5) | (SDA << 10))
chip.write(ENG_A, R_MISC, 1 | (SCL << 3) | (1 << 8) | (1 << 10) | (1 << 13))
chip.write(ENG_A, R_INCFG, SDA)
chip.drain(ENG_A)
chip.start(ENG_A)
time.sleep_ms(5)


def xfer(word):
    chip.write(ENG_A, R_TX, word)
    t = time.ticks_ms()
    while chip.rx_level(ENG_A) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine A: is the kit loaded?")
    return chip.read(ENG_A, R_RX)


def start(): chip.write(ENG_A, R_TX, L["start"] << 11); time.sleep_ms(1)
def stop(): chip.write(ENG_A, R_TX, L["stop"] << 11); time.sleep_ms(1)
def send(b): return xfer(L["xfer"] << 11 | b << 3 | 1 << 2) == b << 1
def recv(ack): return (xfer(L["xfer"] << 11 | 0xFF << 3 | (0 if ack else 1) << 2) >> 1) & 0xFF


def read_seq(mem, n):
    start(); ok = send(DEV << 1) and send(mem >> 8) and send(mem & 255)
    start(); ok = ok and send(DEV << 1 | 1)
    out = [recv(i < n - 1) for i in range(n)]
    stop()
    return out if ok else None


before = read_seq(MEM, N)
print("0x%04X before: %s" % (MEM, " ".join("%02X" % b for b in before) if before else "READ FAILED"))
start(); ok = send(DEV << 1) and send(MEM >> 8) and send(MEM & 255)
for _ in range(N):
    ok = ok and send(0xFF)
stop()
t = time.ticks_ms()
while True:
    start(); a = send(DEV << 1); stop()
    if a or time.ticks_diff(time.ticks_ms(), t) > 50:
        break
after = read_seq(MEM, N)
print("0x%04X after:  %s" % (MEM, " ".join("%02X" % b for b in after) if after else "READ FAILED"))
chip.stop(ENG_A)
print("PASS" if ok and after == [0xFF] * N else "FAIL")
