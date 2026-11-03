# Bench wiring sheet (3 Nov 2026, bench rebuilt from scratch)

Everything is **3.3 V logic**. The FPGA and the ESP32 pins are not 5 V tolerant. One common ground between every
board. Check each lead by continuity to the labelled pad before blaming the design (`programs/read_pins.asm`
shows what the chip sees on every pin).

## 1. Core: MachXO3L kit (header J4) to the ESP32 host

These eight leads run the whole regression (`esp32\rerun.ps1`, command `r`). Fit these first and run `r`
before adding anything else. The ID register should read **0x0022** (spec 2, two engines on the FPGA).

| J4 hole | Ball | Chip signal | ESP32 GPIO | Notes |
|---|---|---|---|---|
| 3 | K12 | CS | 5 | host SPI |
| 5 | M14 | MOSI | 23 | host SPI |
| 7 | L14 | MISO | 19 | host SPI |
| 9 | M15 | SCK | 18 | host SPI |
| 11 | GND | GND | GND | common ground |
| 4 | K13 | IRQ | 4 | high while any engine has data |
| 6 | N14 | engine pin 0 | 16 | engine A's UART out, ESP32 Serial2 RX |
| 26 | G15 | engine pin 15 | 17 | glitch filter test: ESP32 sends pulses into the chip |

J4 holes 1 and 2 are the kit's 3.3 V: usable for pull-ups, never connect them to the ESP32's 3.3 V.
The kit's own USB programs it (`bash fpga/machxo3/build.sh load`, volatile SRAM only, never the NVCM).
The ESP32 is on COM7 (`esp32\upload_and_watch.ps1 -Sketch chip_test`).

## 2. I2C: engine pins 2 and 3

| J4 hole | Ball | Engine pin | Bus | ESP32 as slave (`-Cmd i`) | UNO R3 as slave (`-Cmd n`) |
|---|---|---|---|---|---|
| 10 | M16 | 2 | SCL | GPIO 22 | A5 |
| 13 | L15 | 3 | SDA | GPIO 21 | A4 |

- One 5.1 k pull-up from SCL to 3.3 V and one from SDA to 3.3 V (3.3 V from J4-1 or the UNO's 3.3 V pin; one source).
- UNO ground to the common ground; the UNO sketch (`arduino/i2c_slave_nano`, COM11) switches its own 5 V pull-ups off.
- Never both slaves at once: both answer at 0x50. Unplug the UNO's A4/A5 for `-Cmd i`.

## 3. SPI master to the 74HC595: engine pins 4 to 7

| J4 hole | Ball | Engine pin | Signal | 74HC595 pin |
|---|---|---|---|---|
| 14 | L16 | 4 | SCK | 11 SRCLK |
| 15 | K14 | 5 | MOSI | 14 SER |
| 16 | K16 | 6 | MISO | 9 QH' (serial out) |
| 17 | K15 | 7 | CS / latch | 12 RCLK |

595 power: pin 16 VCC = 3.3 V, pin 8 GND, pin 13 OE = GND (outputs on), pin 10 SRCLR = 3.3 V (not clearing).
LEDs: QA..QH = pins 15, 1, 2, 3, 4, 5, 6, 7, each through about 330 ohms to ground (long leg to the 595).
Test `-Cmd s`: every transfer returns the previous byte through QH'; the run ends on 0x55, so QA (pin 15) = high.
Last night (before the rebuild) the LEDs stayed dark and MISO read 0 with the chip side confirmed good: meter the
four power pins first, then QA after a run, then the QH' lead.

## 4. The whole of J4 (for anything new)

| J4 holes | Balls | Chip pins | Engine pins | Direction |
|---|---|---|---|---|
| 6, 8, 10, 13, 14, 15, 16, 17 | N14 N16 M16 L15 L16 K14 K16 K15 | uio[0..7] | 0-7 | in and out (open drain able) |
| 18, 19, 20 | J14 H14 J15 | uo_out[2..4] | 8-10 | out only |
| 23, 24, 25 | J16 H15 H16 | uo_out[5..7] | 11-13 | out only |
| 26, 27, 28, 29, 30 | G15 G16 F15 F16 E15 | ui_in[3..7] | 15-19 | in only |
| 1, 2 | 3.3 V | | | |
| 11, 12 | GND | | | |

Kit LEDs: P16 lights for IRQ, N15 is the heartbeat (they light when driven low).

## 5. Cyclone IV EP4CE6 board (arrived 3 Nov 2026)

Pin locations are still to be chosen in `fpga/cyclone4/chip_c4.qsf`. The same eight ESP32 leads of section 1 move
across to whatever header pins we assign; the chip clock is 50 MHz there, so set `CHIP_HZ = 50e6` in the sketch
(SPI goes to 4 MHz). Its JTAG is the USB Blaster. Add the table here once the pins are picked.

## Order of work after replugging

1. Section 1 only. Load the kit, upload the sketch, `rerun.ps1` (command `r`): ID 0x0022, 0 problems.
2. Add section 2. `rerun.ps1 -Cmd i` (ESP32 slave) or `-Cmd n` (UNO slave).
3. Add section 3. `rerun.ps1 -Cmd s`.
