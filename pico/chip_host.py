"""MicroPython host for the protocol chip, on a Raspberry Pi Pico 2 (RP2350). The same job esp32/chip_test does, in Python,
and the same job the Tiny Tapeout demo board's RP2040 will do for the real chip: everything goes through the 16-bit SPI host
port (docs/host_port.md): command [15] read, [14:12] engine, [5:0] register, then one 16-bit word.

Wiring (Pico pin -> chip, the kit's header J4; SPI0 on its default pins, GND between SCK and MOSI):
    GP17 (pin 22) CS    -> J4-3        GP19 (pin 25) MOSI -> J4-5        GP16 (pin 21) MISO <- J4-7
    GP18 (pin 24) SCK   -> J4-9        GP20 (pin 26) IRQ  <- J4-4        GND (pin 23) -> J4-11
Copy to the Pico with pico/put.ps1, run with pico/run.ps1.
"""
from machine import Pin, SPI
import time

R_CTRL, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG = 0x20, 0x21, 0x22, 0x23, 0x24, 0x25
R_TX, R_RX, R_STATUS, R_FILTER, R_ID = 0x26, 0x27, 0x28, 0x29, 0x2A
ENG_A, ENG_B, ENG_C = 0, 1, 2


def wrap_reg(start, bottom, top):
    return start | (bottom << 5) | (top << 10)


class Chip:
    def __init__(self, chip_hz=12_000_000, spi_hz=1_000_000):
        self.chip_hz = chip_hz
        self.spi = SPI(0, baudrate=spi_hz, polarity=0, phase=0, bits=8, firstbit=SPI.MSB,
                       sck=Pin(18), mosi=Pin(19), miso=Pin(16))
        self.cs = Pin(17, Pin.OUT, value=1)
        self.irq = Pin(20, Pin.IN)

    @staticmethod
    def cmd(rd, eng, reg):
        return (0x8000 if rd else 0) | ((eng & 7) << 12) | (reg & 0x3F)

    def write(self, eng, reg, value):
        c = self.cmd(False, eng, reg)
        self.cs(0); time.sleep_us(2)
        self.spi.write(bytes((c >> 8, c & 255, (value >> 8) & 255, value & 255)))
        time.sleep_us(2); self.cs(1); time.sleep_us(5)

    def read(self, eng, reg):
        c = self.cmd(True, eng, reg)
        self.cs(0); time.sleep_us(2)
        self.spi.write(bytes((c >> 8, c & 255)))
        d = self.spi.read(2)
        time.sleep_us(2); self.cs(1); time.sleep_us(5)
        return (d[0] << 8) | d[1]

    def load_program(self, eng, words):
        """One burst of 32 words to the program memory (the engine must be stopped); unused words are zero."""
        b = bytearray(2 + 64)
        c = self.cmd(False, eng, 0x00)
        b[0], b[1] = c >> 8, c & 255
        for i, w in enumerate(words[:32]):
            b[2 + 2 * i], b[3 + 2 * i] = (w >> 8) & 255, w & 255
        self.cs(0); time.sleep_us(2)
        self.spi.write(b)
        time.sleep_us(2); self.cs(1); time.sleep_us(5)

    def chip_id(self):
        return self.read(ENG_A, R_ID)

    def drain(self, eng):
        while self.read(eng, R_STATUS) & 0x70:
            self.read(eng, R_RX)

    def rx_level(self, eng):
        return (self.read(eng, R_STATUS) >> 4) & 7

    def stop(self, eng):
        self.write(eng, R_CTRL, 0)

    def start(self, eng):
        self.write(eng, R_CTRL, 1)
