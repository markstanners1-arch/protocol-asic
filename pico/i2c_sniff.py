"""I2C sniffer on the chip, from the Pico (4 Nov 2026): engine A runs programs/i2c_master.asm to the AT24C256 (SCL = engine
pin 2 = J4-10, SDA = pin 3 = J4-13) while engine B runs programs/i2c_sniff.asm on the same two pads and reports every byte
it sees with its ACK bit (word = byte << 1 | 1 if NAKed). The master's own reply for each byte is in the same format
(the byte as it went on the wire, then the ACK slot), so the check is exact: the watcher's list must equal the master's.
Transactions, at 100 kHz and again at 400 kHz: probe 0x50 (ACK), probe 0x57 (nobody: NAK), a 4-byte page write at
0x0020, ACK polling until the write cycle ends, a random read of the 4 bytes (repeated START), the original put back.
No leads to add: engine B reads the pads engine A drives. PASS only if every transaction matched byte for byte."""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
DEV, MEM, N = 0x50, 0x0020, 4
chip = Chip(CHIP_HZ)
L = LABELS["i2c_master"]
ok = True
seen = []            # what engine B reported since the last take()
heard = []           # what engine A replied, same format


def setup(khz):
    words, wb, wt = PROGRAMS["i2c_master"]
    chip.stop(ENG_A); chip.stop(ENG_B)
    chip.write(ENG_A, R_FILTER, 0)
    chip.load_program(ENG_A, words)
    chip.write(ENG_A, R_CLKDIV, round(CHIP_HZ / (10 * khz * 1000)) - 1)             # 10 ticks a bit
    chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_A, R_OUTCFG, SDA | (1 << 5) | (SDA << 10))
    chip.write(ENG_A, R_MISC, 1 | (SCL << 3) | (1 << 8) | (1 << 10) | (1 << 13))
    chip.write(ENG_A, R_INCFG, SDA)
    words, wb, wt = PROGRAMS["i2c_sniff"]
    chip.load_program(ENG_B, words)
    chip.write(ENG_B, R_CLKDIV, 0)                                                   # every clock: SCL at 400 kHz is 30 ticks
    chip.write(ENG_B, R_WRAP, wrap_reg(0, wb, wt))
    chip.write(ENG_B, R_OUTCFG, 0)
    chip.write(ENG_B, R_MISC, 1 << 11)                                               # out_right 1, in_right 0 (MSB first)
    chip.write(ENG_B, R_INCFG, SCL | (SDA << 5))                                     # in_base = SCL, jmp_pin = SDA
    chip.drain(ENG_A); chip.drain(ENG_B)
    chip.start(ENG_B)
    chip.start(ENG_A)
    time.sleep_ms(5)


def listen():
    while chip.rx_level(ENG_B):
        seen.append(chip.read(ENG_B, R_RX))


def xfer(word):
    chip.write(ENG_A, R_TX, word)
    t = time.ticks_ms()
    while chip.rx_level(ENG_A) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine A: is the kit loaded?")
    r = chip.read(ENG_A, R_RX)
    heard.append(r)
    listen()
    return r


def start():
    chip.write(ENG_A, R_TX, L["start"] << 11); time.sleep_ms(1); listen()


def stop():
    chip.write(ENG_A, R_TX, L["stop"] << 11); time.sleep_ms(1); listen()


def send(b):
    return xfer(L["xfer"] << 11 | b << 3 | 1 << 2) == b << 1


def recv(ack):
    return (xfer(L["xfer"] << 11 | 0xFF << 3 | (0 if ack else 1) << 2) >> 1) & 0xFF


def fmt(words):
    return " ".join("%02X%s" % (w >> 1, "-" if w & 1 else "+") for w in words)     # + acked, - not


def check(name):
    global ok, seen, heard
    time.sleep_ms(2); listen()
    good = seen == heard
    ok = ok and good
    print("  %-34s master: %s" % (name, fmt(heard)))
    print("  %-34s watcher: %s  %s" % ("", fmt(seen), "ok" if good else "WRONG"))
    seen, heard = [], []


def probe(addr):
    start(); r = send(addr << 1); stop()
    return r


def read_seq(mem, n):
    start(); send(DEV << 1); send(mem >> 8); send(mem & 255)
    start(); send(DEV << 1 | 1)
    out = [recv(i < n - 1) for i in range(n)]
    stop()
    return out


def write_page(mem, data):
    start(); send(DEV << 1); send(mem >> 8); send(mem & 255)
    for d in data:
        send(d)
    stop()


def wait_write():
    t = time.ticks_ms()
    while not probe(DEV):
        if time.ticks_diff(time.ticks_ms(), t) > 50:
            return None
    return time.ticks_diff(time.ticks_ms(), t)


print("chip ID %04X" % chip.chip_id())
for khz in (100, 400):
    setup(khz)
    print("==== %d kHz: engine A to the AT24C256, engine B watching the same pads (byte+ = acked, byte- = not) ====" % khz)
    a = probe(DEV); check("probe 0x%02X (expect acked)" % DEV)
    b = probe(0x57); check("probe 0x57 (expect nobody)")
    if not a or b:
        print("  FAIL: the bus is not as expected (0x50 %s, 0x57 %s)" % ("acked" if a else "silent", "acked" if b else "silent"))
        ok = False
    before = read_seq(MEM, N); check("read 4 as found at 0x%04X" % MEM)
    pattern = [((i * 53) + (time.ticks_ms() & 0xFF)) & 0xFF for i in range(N)]
    write_page(MEM, pattern); check("page write of 4")
    cyc = wait_write(); check("ACK polling, %s ms" % cyc)
    after = read_seq(MEM, N); check("random read back")
    print("  wrote %s, read back %s  %s" % (" ".join("%02X" % x for x in pattern), " ".join("%02X" % x for x in after), "ok" if after == pattern else "WRONG"))
    ok = ok and after == pattern
    write_page(MEM, before); wait_write(); check("original put back + polling")
    back = read_seq(MEM, N); check("read back the original")
    ok = ok and back == before
chip.stop(ENG_A); chip.stop(ENG_B)
print("PASS" if ok else "FAIL")
