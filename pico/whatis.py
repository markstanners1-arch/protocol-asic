"""'What is this chip?': the Pico asks the chip to describe itself and everything wired to it. All measuring is done by the engines.
  1. the chip's own ID register: host port spec and engine count
  2. an I2C scan: engine A (programs/i2c_master.asm) tries every address 0x08-0x77, and a short table guesses what answered
  3. a pin survey: engine B reads the pins' levels, then (programs/measure_pulse.asm) watches each pin for 0.4 s and reports the low
     pulses it timed, to a microsecond
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script whatis.py -Seconds 40"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_TX, R_RX, R_FILTER
from programs import PROGRAMS, LABELS

CHIP_HZ = 12_000_000
SCL, SDA = 2, 3
chip = Chip(CHIP_HZ)

# ---- 1. the ID register
cid = chip.chip_id()
print("==== what is this chip? ====")
print("ID register 0x%04X: host port spec %d, %d engines, clocked at %.0f MHz here" % (cid, cid >> 4, cid & 15, CHIP_HZ / 1e6))

# ---- 2. I2C scan with engine A
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
            return None
    return chip.read(ENG_A, R_RX)


def probe(addr):
    chip.write(ENG_A, R_TX, L["start"] << 11); time.sleep_ms(1)
    r = xfer(L["xfer"] << 11 | (addr << 1) << 3 | 1 << 2)
    chip.write(ENG_A, R_TX, L["stop"] << 11); time.sleep_ms(1)
    return r == (addr << 1) << 1


GUESS = {0x20: "PCF8574 or MCP23008 I/O expander", 0x27: "PCF8574 LCD backpack", 0x3F: "PCF8574A LCD backpack",
         0x3C: "SSD1306 OLED", 0x3D: "SSD1306 OLED", 0x40: "INA219, Si7021 or HTU21D", 0x48: "ADS1115, PCF8591 or TMP102",
         0x57: "AT24C32/64 on a DS3231 module (or an AT24C with A0-A2 high)",
         0x60: "MCP4725 DAC (A0 low; pico/mcp4725.py)", 0x61: "MCP4725 DAC (A0 high)", 0x62: "MCP4725 DAC (A1 part, A0 low)", 0x63: "MCP4725 DAC (A1 part, A0 high)",
         0x68: "DS3231 RTC or MPU6050: read register 0x75 (0x68 = MPU6050; pico/ds3231.py does)", 0x69: "MPU6050 (AD0 high)",
         0x76: "BMP280 / BME280", 0x77: "BMP180 / BMP280 / BME280"}
print("\nI2C scan (engine A, SCL pin %d, SDA pin %d, 100 kHz): addresses 0x08-0x77" % (SCL, SDA))
found = []
for a in range(0x08, 0x78):
    if probe(a):
        g = GUESS[a] if a == 0x57 else "AT24Cxx EEPROM (address pins A0-A2 = %d)" % (a - 0x50) if 0x50 <= a <= 0x56 else "EEPROM identification page (24Cxxx parts with an ID page answer here as well as at 0x50)" if 0x58 <= a <= 0x5F else GUESS.get(a, "unknown")
        found.append(a)
        print("  0x%02X answered: %s" % (a, g))
if not found:
    print("  nothing answered (no device, or no pull-ups / power on the bus)")
chip.stop(ENG_A)

# ---- 3. pin survey with engine B
NAMES = {0: "engine A UART out (to the ESP32)", 1: "IR receiver", 2: "I2C SCL", 3: "I2C SDA", 4: "keypad column 1", 5: "keypad column 2",
         6: "keypad column 3", 7: "keypad column 4", 15: "ESP32 test pulses in", 16: "keypad row 1", 17: "keypad row 2",
         18: "keypad row 3", 19: "keypad row 4"}


def snapshot(base):
    w, b, t = PROGRAMS["read_pins"]
    chip.stop(ENG_B)
    chip.load_program(ENG_B, w)
    chip.write(ENG_B, R_CLKDIV, 0)
    chip.write(ENG_B, R_WRAP, wrap_reg(0, b, t))
    chip.write(ENG_B, R_OUTCFG, 0); chip.write(ENG_B, R_MISC, 0); chip.write(ENG_B, R_INCFG, base)
    chip.drain(ENG_B)
    chip.start(ENG_B)
    v = 0
    for _ in range(8):
        v = chip.read(ENG_B, R_RX)
    chip.stop(ENG_B)
    return v


lv = snapshot(0)
lv15 = snapshot(15)
level = {p: (lv >> p) & 1 for p in range(0, 15)}
level.update({p: (lv15 >> (p - 15)) & 1 for p in range(15, 20)})


def watch(pin, ms=400):
    w, b, t = PROGRAMS["measure_pulse"]
    chip.stop(ENG_B)
    chip.load_program(ENG_B, w)
    chip.write(ENG_B, R_CLKDIV, round(CHIP_HZ / 1e6) - 1)          # 1 us tick
    chip.write(ENG_B, R_WRAP, wrap_reg(0, b, t))
    chip.write(ENG_B, R_OUTCFG, 0); chip.write(ENG_B, R_MISC, 0); chip.write(ENG_B, R_INCFG, pin)
    chip.drain(ENG_B)
    chip.start(ENG_B)
    got = []
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        if chip.rx_level(ENG_B):
            got.append(chip.read(ENG_B, R_RX))
    chip.stop(ENG_B)
    return got


print("\nPin survey (engine B): level now, then low pulses timed in 0.4 s. Pins 0-7 have pull-ups in this kit build, so 'high' alone proves no lead;")
print("pins 8-13 are output only and read 0; 15-19 are input only with pull-downs. Press a remote button at the receiver during the survey to see it.")
for p in list(range(0, 8)) + list(range(15, 20)):
    pulses = watch(p)
    what = NAMES.get(p, "")
    if pulses:
        s = "%d low pulse%s, %d to %d us" % (len(pulses), "" if len(pulses) == 1 else "s", min(pulses), max(pulses))
    else:
        s = "quiet"
    print("  pin %2d  %-4s %-34s %s" % (p, "high" if level[p] else "low", what, s))
print("\nPASS" if cid & 15 >= 2 and (cid >> 4) == 2 else "\nFAIL: the ID register is wrong")
