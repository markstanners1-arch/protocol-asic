# Bench wiring sheet (3 Nov 2026, bench rebuilt from scratch)

One wire per row: **FROM** one end **TO** the other, **AND** a third end where the wire has one (a pull-up, a second
board). Kit pins are written **J4-n (ball)**: n is the numbered hole on header J4, the ball name (K12...) is the FPGA's
own label printed beside it, the same connection under a second name, for checking by continuity. **Go by the hole number**: the ball letters H and M (H16 is hole 25, M16 is hole 10) are easy to misread on the silkscreen. **Engine pin**
numbers (0-19) are what the chip's programs call that pin. Everything is **3.3 V logic** (FPGA and ESP32 pins are not
5 V tolerant); one common ground between every board. `programs/read_pins.asm` shows what the chip sees on every pin.
Section 6 (4 Nov) adds the keypad, IR receiver and ultrasonic. The same sheet as a landscape PDF for the monitor: `docs/bench_wiring.pdf` (`python docs/make_bench_wiring_pdf.py`).

## 1. Core: kit to ESP32 host

Fit these eight first, then `esp32\rerun.ps1` (command `r`): the ID register reads **0x0022**, 0 problems.

| FROM | TO | AND | What it is |
|---|---|---|---|
| J4-3 (K12) | ESP32 GPIO 5 | | CS, host SPI |
| J4-5 (M14) | ESP32 GPIO 23 | | MOSI, host SPI |
| J4-7 (L14) | ESP32 GPIO 19 | | MISO, host SPI |
| J4-9 (M15) | ESP32 GPIO 18 | | SCK, host SPI |
| J4-11 (GND) | ESP32 GND | every other board's GND | common ground |
| J4-4 (K13) | ESP32 GPIO 4 | | IRQ: high while any engine has data |
| J4-6 (N14) | ESP32 GPIO 16 | | engine pin 0: engine A's UART out, into ESP32 Serial2 RX |
| J4-26 (G15) | ESP32 GPIO 17 | | engine pin 15: the ESP32 sends test pulses into the chip (glitch filter) |

J4-1 and J4-2 are the kit's 3.3 V: for pull-ups only, never joined to the ESP32's 3.3 V.
Kit: `bash fpga/machxo3/build.sh load` (volatile SRAM only, never the NVCM). ESP32: the scripts find its CH340 port themselves:
`esp32\upload_and_watch.ps1 -Sketch chip_test`.

## 2. I2C bus (engine pins 2 = SCL, 3 = SDA)

ESP32 as the slave: `rerun.ps1 -Cmd i`. UNO R3 as the slave: `-Cmd n`.

| FROM | TO | AND | What it is |
|---|---|---|---|
| J4-10 (M16) SCL | ESP32 GPIO 22 or UNO A5 | 5.1 k resistor to 3.3 V | SCL, engine pin 2 |
| J4-13 (L15) SDA | ESP32 GPIO 21 or UNO A4 | 5.1 k resistor to 3.3 V | SDA, engine pin 3 |
| UNO GND | common ground | | only when the UNO is the slave; its sketch switches its own 5 V pull-ups off |
| 3.3 V for the two pull-ups | J4-1 or the UNO's 3.3 V pin | | one source, not both |

**Never both slaves at once** (both answer at 0x50): unplug the UNO's A4 and A5 for `-Cmd i`.
UNO sketch: `arduino/i2c_slave_nano` on COM11.

## 3. SPI master to the 74HC595 (engine pins 4 to 7)

`rerun.ps1 -Cmd s`.

| FROM | TO | AND | What it is |
|---|---|---|---|
| J4-14 (L16) | 595 pin 11 SRCLK | | SCK, engine pin 4 |
| J4-15 (K14) | 595 pin 14 SER | | MOSI, engine pin 5 |
| J4-16 (K16) | 595 pin 9 QH' | | MISO, engine pin 6: the 595's serial out comes back |
| J4-17 (K15) | 595 pin 12 RCLK | | CS / latch, engine pin 7 |
| 595 pin 16 VCC | 3.3 V | | power |
| 595 pin 8 GND | common ground | | power |
| 595 pin 13 OE | GND | | outputs enabled |
| 595 pin 10 SRCLR | 3.3 V | | not clearing |
| 595 pins 15, 1, 2, 3, 4, 5, 6, 7 (QA..QH) | LED long leg | LED short leg -> 330 ohm -> GND | red, yellow or green LEDs only: white and blue need ~3 V and stay dim at 3.3 V, and the flat-topped ones from the drawer never lit (3 Nov); the run ends on 0x55 so QA (pin 15) is high |

Before the rebuild the LEDs stayed dark with the chip side proven good: meter pins 16, 8, 13, 10 first, then pin 15
after a run, then the QH' lead.

## 4. Every J4 hole the chip uses (for anything new)

| J4 holes | Balls | Engine pins | Direction |
|---|---|---|---|
| 6, 8, 10, 13, 14, 15, 16, 17 | N14, N16, M16, L15, L16, K14, K16, K15 | 0, 1, 2, 3, 4, 5, 6, 7 | in and out (open drain able) |
| 18, 19, 20 | J14, H14, J15 | 8, 9, 10 | out only |
| 23, 24, 25 | J16, H15, H16 | 11, 12, 13 | out only |
| 26, 27, 28, 29, 30 | G15, G16, F15, F16, E15 | 15, 16, 17, 18, 19 | in only |
| 1, 2 | 3.3 V | | |
| 11, 12 | GND | | |

Holes and balls pair up in order: hole 6 is ball N14 (engine pin 0), hole 8 is N16 (pin 1), and so on along each row.
Kit LEDs: P16 lights for IRQ, N15 is the heartbeat (they light when driven low).

## 5. Cyclone IV board (the black EP4CE6E22C8N core board, arrived 3 Nov 2026)

Pins are the FPGA pin numbers printed on the headers. Everything sits on the **right-hand header, 38 to 72** (one bank,
jumper VB at 3.3; the left bank's jumper VC also at 3.3). Clock 50 MHz on pin 24, serial RX 23 / TX 10 (CH340 on the
USB-C, power only for us), LEDs on 1 (IRQ) and 2 (heartbeat). Program over the 10-pin JTAG header with a **USB Blaster**
(ordered 3 Nov; the driver is in): `bash fpga/cyclone4/build.sh load` (volatile SRAM, never the flash). In the sketch set
`CHIP_HZ = 50e6` (SPI goes to 4 MHz, filter prescale to 4). This board runs **three engines** (ID reads 0x0023); the kit runs two.

| FROM (Cyclone pin) | TO | What it is |
|---|---|---|
| 38 | ESP32 GPIO 5 | CS |
| 39 | ESP32 GPIO 18 | SCK |
| 42 | ESP32 GPIO 23 | MOSI |
| 43 | ESP32 GPIO 19 | MISO |
| 44 | ESP32 GPIO 4 | IRQ |
| 46 | ESP32 GPIO 16 | engine pin 0 (UART out) |
| 67 | ESP32 GPIO 17 | engine pin 15 (pulses in) |
| GND (header end) | ESP32 GND | common ground |
| 49, 50, 51, 52, 53, 54, 55 | | engine pins 1-7 (two-way): I2C SCL = 50, SDA = 51; SPI SCK/MOSI/MISO/CS = 52/53/54/55 |
| 58, 59, 60, 64, 65, 66 | | engine pins 8-13 (out only) |
| 68, 69, 70, 71 | | engine pins 16-19 (in only) |

## 6. Keypad, IR receiver and ultrasonic (4 Nov 2026, the Elegoo kit parts)

**Keypad** (`rerun.ps1 -Cmd y`, engine B, `programs/keypad.asm`). The membrane keypad's tail has eight pins; with the keys
facing you and the tail at the bottom, pin 1 is on the left: pins 1-4 are the **rows** top to bottom, 5-8 the **columns**
left to right. The chip pulls one column low at a time and reads the rows, so the four rows need pull-ups.
The 595's four leads share J4-14 to 17: unplug them (or leave the 595 unpowered) while the keypad is in.

| FROM | TO | AND | What it is |
|---|---|---|---|
| keypad pin 1 (row 1: 1 2 3 A) | J4-27 (G16) | 10 k resistor to J4-1 (3.3 V) | row 1, engine pin 16 |
| keypad pin 2 (row 2: 4 5 6 B) | J4-28 (F15) | 10 k resistor to J4-1 | row 2, engine pin 17 |
| keypad pin 3 (row 3: 7 8 9 C) | J4-29 (F16) | 10 k resistor to J4-1 | row 3, engine pin 18 |
| keypad pin 4 (row 4: * 0 # D) | J4-30 (E15) | 10 k resistor to J4-1 | row 4, engine pin 19 |
| keypad pin 5 (column 1: 1 4 7 *) | J4-14 (L16) | | column 1, engine pin 4 |
| keypad pin 6 (column 2: 2 5 8 0) | J4-15 (K14) | | column 2, engine pin 5 |
| keypad pin 7 (column 3: 3 6 9 #) | J4-16 (K16) | | column 3, engine pin 6 |
| keypad pin 8 (column 4: A B C D) | J4-17 (K15) | | column 4, engine pin 7 |

The sketch prints the raw 16-bit map with each key name (bit 4*(3-c)+r). If every key comes out as its mirror
(1 reads as *, say), the tail is numbered the other way round: swap the two groups of four.

**IR receiver module** (KY-022, three pins, happy at 3.3 V; program to follow). Point any of the remotes at it.

| FROM | TO | AND | What it is |
|---|---|---|---|
| module S (signal) | J4-8 (N16) | | engine pin 1: idles high, pulses low under the 38 kHz bursts |
| module + (VCC) | J4-1 (3.3 V) | | power |
| module - (GND) | common ground | | power |

**Ultrasonic HC-SR04** (5 V part: its echo output must be divided down; program to follow). One at a time with the IR
receiver, they share J4-8.

| FROM | TO | AND | What it is |
|---|---|---|---|
| HC-SR04 VCC | ESP32 5 V pin (VIN) | | 5 V power |
| HC-SR04 GND | common ground | | power |
| HC-SR04 Trig | J4-18 (J14) | | engine pin 8 (out only): the 10 us trigger pulse; 3.3 V is enough |
| HC-SR04 Echo | 1 k resistor | the other end to J4-8 (N16) and a 2 k resistor to GND | echo pulse (5 V) divided to 3.3 V, engine pin 1; 58 us per cm |

## If it doesn't answer: bench helpers (`esp32
erun.ps1 -Cmd <letter>`)

| Command | Does | Tells you |
|---|---|---|
| `p` | lead probe: reads MISO and IRQ with the ESP32's pull-up then pull-down, then one raw ID read | a FLOATING pin = that lead open or in the wrong hole; ID 0x0000 with MISO driven = CS, SCK or MOSI not arriving; 0xFFFF = MISO open |
| `q` | engine B keeps data waiting for 15 s, GPIO 4 polled | the IRQ lead (and the kit's IRQ LED P16) |
| `b` | I2C wire check: engine B reads all 20 engine pins while the ESP32 pulls its SDA, then its SCL, low | the chip pin each I2C lead actually reaches (expect SDA = pin 3, SCL = pin 2); nothing moving = that lead is in a hole the chip cannot read (3 Nov: H16, hole 25, read as M16) |
| `k` | GPIO 22 (the ESP32's SCL) held low for 30 s | time to meter both ends of the SCL lead |
| `l` | ID reads over and over for 30 s | a repeating burst on CS, SCK, MOSI and MISO for the oscilloscope; MISO should read 0x0022 |
| `y` | keypad: names every key pressed until any character is sent | section 6 wiring; a key that never shows = its row or column lead; every key mirrored = the tail numbered the other way |

Lessons of 3 Nov: writes working but reads all zero = the MISO lead's J4 end in a hole that is held low (11/12 are GND,
18-25 are driven low when no engine owns them); everything zero and nothing received = CS/SCK/MOSI; everything 0xFFFF
= no leads at all. The kit's SRAM build is lost on any power blip: reload it (`bash fpga/machxo3/build.sh load`).

## Oscilloscope (Hantek DSO5102P)

Pictures go to a **FAT32 stick (32 GB or under) in the front socket**; the rear USB needs a driver Windows 11 refuses.
Probes clip onto spare pins in breadboard rows the leads pass through, grounds to the ground rail; probe switches and
channel settings both at 10x. For I2C: CH1 SCL, CH2 SDA, 1 V/div, 20 us/div for a byte or 100 us/div for a
transaction, trigger CH2 falling at 1.5 V (the START) with holdoff about 1 ms, mode Normal. Signal: `rerun.ps1 -Cmd z`
runs transactions until any key (`-Cmd o` for 60 s); `-Cmd l` is repeating host-port reads for SCK/MISO.

## Order of work after replugging

1. Section 1 only. Load the kit, upload the sketch, `rerun.ps1` (command `r`): ID 0x0022, 0 problems.
2. Add section 2. `rerun.ps1 -Cmd i` (ESP32 slave) or `-Cmd n` (UNO slave).
3. Add section 3. `rerun.ps1 -Cmd s`.
4. Keypad: section 6 (the 595's four leads out), `rerun.ps1 -Cmd y`, press keys.
