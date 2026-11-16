"""MCP4725 12-bit I2C DAC from the Pico: engine A runs programs/i2c_master.asm (SCL = engine pin 2 = J4-10, SDA = pin 3 = J4-13)
at 400 kHz to the DAC module on the same bus as the EEPROMs. Checked against a modelled device; not yet run on hardware.
Wiring (sheet section 12): module VDD/VCC -> J4-1 or J4-2 (3.3 V only), GND -> the negative rail (wired to J4-11 or 12),
SCL -> J4-10, SDA -> J4-13, OUT -> the meter's red lead / the scope probe (black lead to the rail). A0 pad as the module has it.
The address is 0x60 or 0x61 (A0 pad) on the MCP4725A0 most modules carry, 0x62/0x63 on an A1 part, 0x64/0x65 on an A2: the
script probes 0x60-0x67 and uses the first that answers.

Fast-mode write: after the address, two bytes per value: [0 0 PD1 PD0 D11 D10 D9 D8] [D7 .. D0], PD = 00 = normal operation.
The DAC output moves after the second byte's ACK, and pairs can follow each other inside one transaction with no restart, so a
waveform is one long write: address once, then two bytes a step. The output is VDD * code / 4096: with the 3.3 V supply,
0 -> 0 V, 2048 -> 1.65 V, 4095 -> 3.30 V (to within the module's supply: meter J4-1 to be exact). Fast writes do not touch the
DAC's EEPROM, so the power-up value is unchanged.

The test, in order:
  1. probe 0x60-0x67: one address must answer
  2. 0 V, half scale, full scale, 3 s each: meter the OUT pin against the printed expectation (0.00, 1.65, 3.30 V)
  3. sawtooth, 64 steps (0, 64, 128 .. 4032, then back to 0) for 10 s: the wire allows 18 bits a step (two bytes with ACKs) =
     45 us at 400 kHz = 2.88 ms a ramp = 347 Hz; the host round trips (a 16-bit word out and the reply read back per byte) take
     longer than that, so the script times the ramps it actually made and prints the measured frequency, which is what the
     scope must show (CH1 on OUT, 1 V/div, 1 ms/div at first; trigger on the falling flyback)
  4. triangle, 64 up and 64 down, 10 s: half the sawtooth's frequency
  5. back to 0 V
PASS = the address answered and every byte of every write was acked (the voltages and the scope trace are checked by meter and scope).
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script mcp4725.py -Seconds 40"""
import time
from chip_host import Chip, wrap_reg, ENG_A, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
KHZ = 400                              # the MCP4725 takes 400 kHz; so do the AT24Cs sharing the bus
VDD = 3.3
STEPS = 64
RAMP_S = 10

chip = Chip(CHIP_HZ)
L = LABELS["i2c_master"]
words, wb, wt = PROGRAMS["i2c_master"]
chip.stop(ENG_A)
chip.write(ENG_A, R_FILTER, 0)
chip.load_program(ENG_A, words)
chip.write(ENG_A, R_CLKDIV, round(CHIP_HZ / (10 * KHZ * 1000)) - 1)              # 10 ticks a bit
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, SDA | (1 << 5) | (SDA << 10))                        # out and set = SDA
chip.write(ENG_A, R_MISC, 1 | (SCL << 3) | (1 << 8) | (1 << 10) | (1 << 13))     # set_count 1, side-set SCL (directions)
chip.write(ENG_A, R_INCFG, SDA)
chip.drain(ENG_A)
chip.start(ENG_A)
time.sleep_ms(5)
XFER = L["xfer"] << 11


def xfer(word):
    chip.write(ENG_A, R_TX, word)
    t = time.ticks_ms()
    while chip.rx_level(ENG_A) == 0:
        if time.ticks_diff(time.ticks_ms(), t) > 100:
            raise OSError("no reply from engine A: is the kit loaded?")
    return chip.read(ENG_A, R_RX)


def start():
    chip.write(ENG_A, R_TX, L["start"] << 11); time.sleep_ms(1)


def stop():
    chip.write(ENG_A, R_TX, L["stop"] << 11); time.sleep_ms(1)


def send(b):
    """One byte out; True if the slave acked (the reply is the byte as it went on the wire, then a 0 ACK bit)."""
    return xfer(XFER | b << 3 | 1 << 2) == b << 1


def probe(addr):
    start(); ok = send(addr << 1); stop()
    return ok


def set_dac(dev, code):
    """One fast-mode write of a 12-bit code; True if all three bytes were acked."""
    start(); ok = send(dev << 1) and send((code >> 8) & 0x0F) and send(code & 0xFF); stop()
    return ok


def waveform(dev, codes, seconds):
    """Streams codes round and round inside one transaction for the given time, two bytes a step, the two words for a step
    pushed before their replies are read (the FIFOs are 4 deep). Returns (steps done, bad acks, seconds taken)."""
    start()
    ok = send(dev << 1)
    bad = 0 if ok else 1
    n = 0
    t0 = time.ticks_us()
    while time.ticks_diff(time.ticks_us(), t0) < seconds * 1_000_000:
        for c in codes:
            hi, lo = (c >> 8) & 0x0F, c & 0xFF
            chip.write(ENG_A, R_TX, XFER | hi << 3 | 1 << 2)
            chip.write(ENG_A, R_TX, XFER | lo << 3 | 1 << 2)
            while chip.rx_level(ENG_A) < 2:
                pass
            if chip.read(ENG_A, R_RX) != hi << 1:
                bad += 1
            if chip.read(ENG_A, R_RX) != lo << 1:
                bad += 1
            n += 1
    took = time.ticks_diff(time.ticks_us(), t0) / 1e6
    stop()
    return n, bad, took


ok = True
print("==== MCP4725 DAC from the Pico: engine A I2C master, SCL pin %d (J4-10), SDA pin %d (J4-13), %d kHz ====" % (SCL, SDA, KHZ))

# ---- 1. find it
dev = None
for a in range(0x60, 0x68):
    if probe(a):
        dev = a
        break
others = [a for a in (0x50, 0x57, 0x68) if probe(a)]
print("DAC address:            %s   (0x60/0x61 = MCP4725A0, 0x62/0x63 = A1, 0x64/0x65 = A2; the pad A0 picks the low bit)" % ("0x%02X" % dev if dev is not None else "NONE of 0x60-0x67 answered"))
if others:
    print("also on the bus:        %s" % " ".join("0x%02X" % a for a in others))
if dev is None:
    print("FAIL: no DAC: check VCC (3.3 V), ground to the kit, SCL J4-10, SDA J4-13; the other I2C modules answering proves the bus itself")
    chip.stop(ENG_A)
    raise SystemExit

# ---- 2. three levels to meter
for code, name in ((0, "zero"), (2048, "half scale"), (4095, "full scale")):
    w = set_dac(dev, code)
    ok &= w
    print("%-11s code %4d:   %s   meter OUT: expect %.2f V (VDD %.2f V * %d / 4096), 3 s" % (name, code, "acked" if w else "NOT ACKED", VDD * code / 4096, VDD, code))
    time.sleep(3)

# ---- 3. sawtooth
saw = [i * (4096 // STEPS) for i in range(STEPS)]
bits_per_ramp = STEPS * 2 * 9                                        # two bytes a step, 9 clocks each (8 bits and the ACK)
wire_hz = KHZ * 1000 / bits_per_ramp
print("sawtooth, %d steps of %d, %d s: the wire allows %d bits a ramp = %.1f Hz at %d kHz; the host is slower, measuring..." % (STEPS, 4096 // STEPS, RAMP_S, bits_per_ramp, wire_hz, KHZ))
n, bad, took = waveform(dev, saw, RAMP_S)
ramps = n / STEPS
print("  %d steps, %d bad acks, %.2f s: %.1f ramps/s = %.1f Hz on the scope, %.0f us a step   %s" % (n, bad, took, ramps / took, ramps / took, took * 1e6 / n, "ok" if bad == 0 else "WRONG"))
ok &= bad == 0

# ---- 4. triangle
tri = saw + saw[::-1]
n, bad, took = waveform(dev, tri, RAMP_S)
cycles = n / (2 * STEPS)
print("triangle, %d up and %d down, %d s: %d steps, %d bad acks: %.1f Hz on the scope   %s" % (STEPS, STEPS, RAMP_S, n, bad, cycles / took, "ok" if bad == 0 else "WRONG"))
ok &= bad == 0

# ---- 5. back to zero
w = set_dac(dev, 0)
ok &= w
print("back to 0 V:            %s" % ("acked" if w else "NOT ACKED"))
chip.stop(ENG_A)
print("PASS" if ok else "FAIL")
