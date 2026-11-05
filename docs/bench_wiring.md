# Bench wiring sheet (3 Nov 2026, bench rebuilt from scratch)

**5 Nov 2026: the MachXO3L kit is retired from the bench in favour of the Mojo v3 (section 14).** Sections 1 to 4 and 6 to 13
describe the kit's wiring and stay for the record and for the kit's later use as a second board; the modules in sections 9
and 11 to 13 move to the Mojo's engine pins when they are next run. The kit's SRAM is loaded, never its one-time memory, so
`bash fpga/machxo3/build.sh load` brings it back whenever it is wanted.

One wire per row: **FROM** one end **TO** the other, **AND** a third end where the wire has one (a pull-up, a second
board). Kit pins are written **J4-n (ball)**: n is the numbered hole on header J4, the ball name (K12...) is the FPGA's
own label printed beside it, the same connection under a second name, for checking by continuity. **Go by the hole number**: the ball letters H and M (H16 is hole 25, M16 is hole 10) are easy to misread on the silkscreen. **Engine pin**
numbers (0-19) are what the chip's programs call that pin. Everything is **3.3 V logic** (FPGA and ESP32 pins are not
5 V tolerant); one common ground between every board. `programs/read_pins.asm` shows what the chip sees on every pin.
Section 6 (4 Nov) adds the keypad, IR receiver and ultrasonic; section 10 the DALI shield (planned, not yet wired); sections 11-13 the W25Q32 flash, DS3231 clock and MCP4725 DAC modules (due 5 Nov, scripts written, not yet run); section 14 the Mojo v3 with the IO Shield, Pico as host (5 Nov). The same sheet as a landscape PDF for the monitor: `docs/bench_wiring.pdf` (`python docs/make_bench_wiring_pdf.py`).

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

J4-1 and J4-2 are the kit's 3.3 V (printed IO1 on the silkscreen, the bank supply, not a ball name): for pull-ups only, never joined to the ESP32's 3.3 V.
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

**IR receiver module** (`rerun.ps1 -Cmd m`, engine B, `programs/ir_nec.asm`; KY-022, three pins, happy at 3.3 V).
Point any NEC remote at it (this Elegoo kit has no remote, only the receiver and the emitter board). The sketch first reports the line's idle level (must be high),
then prints every frame as address and command with the inverse bytes checked, and "repeat n" while a button is held.
`-Cmd j` prints the raw low-pulse lengths instead (leader 180 ticks of 50 us, bit bursts 11): what the remote really sends.

| FROM | TO | AND | What it is |
|---|---|---|---|
| module S (signal) | J4-8 (N16) | | engine pin 1: idles high, pulses low under the 38 kHz bursts |
| module + (VCC) | J4-2 (3.3 V; or J4-1) | | power |
| module - (GND) | common ground | | power |

The module's pads are marked **G R Y** (green ground, red power, yellow signal): Y is the S lead. The kit also has an IR
**emitter** (KY-005, a clear LED): it must not be on this pin, its LED pulls the line low (seen 4 Nov: `m` read the line
stuck low). Pin 1 has a pull-up in the kit build, so an idle-high reading alone does not prove the receiver is wired.

**IR emitter board** (`rerun.ps1 -Cmd t`: engine A transmits NEC frames, engine B decodes them from the receiver; `programs/ir_tx.asm`).
Face the LED at the receiver's black dome, a few cm apart. A phone camera shows the emitter's flicker as a faint purple glow.

| FROM | TO | AND | What it is |
|---|---|---|---|
| emitter signal (S/Y) | J4-19 (H14) | | engine pin 9, out only: the 38 kHz bursts |
| emitter - (G) | J4-11 or J4-12 (GND) | | ground |
| emitter middle pin | not connected | | unused on this board (the loopback passed with it open) |

**Remote button codes, read on the kit 4 Nov 2026** (`-Cmd m`, twice, the same codes both times; pressed in the order
shown with a stated sequence, so each row is a checked pair). The remote is a Manhattan one (a second, non-LG remote) with NEC timing (9 ms
leader, 562.5 us bursts, repeat frames every 108 ms) but a 16-bit address and a 16-bit command with no inverse rule,
so `m` prints BAD INVERSE for every key: that flag means "not the plain 8-bit NEC layout", not a read error. The
address word is 2916 on every key. A tap gives 2 to 5 repeat frames, a hold keeps repeating at 108 ms.

| Button | Command word | Command byte | Button | Command word | Command byte |
|---|---|---|---|---|---|
| 1 | 5CB7 | B7 | 7 | 5BC7 | C7 |
| 2 | 6CB6 | B6 | 8 | 6BC6 | C6 |
| 3 | 7CB5 | B5 | 9 | 7BC5 | C5 |
| 4 | 0CC2 | C2 | 0 | 3BC9 | C9 |
| 5 | 1CC1 | C1 | POWER | 9CB3 | B3 |
| 6 | 2CC0 | C0 | VOL+ | 2AE0 | E0 |

Mark's LG "smart" remote (the one with the thumb wheel) read the same way, its POWER key: address 04, command 08, both
inverses correct, so standard NEC passes the `m` checks. No Elegoo remote exists on the bench: the kit came with the emitter board only.

**Ultrasonic HC-SR04** (5 V part: its echo output must be divided down; program to follow). One at a time with the IR
receiver, they share J4-8.

| FROM | TO | AND | What it is |
|---|---|---|---|
| HC-SR04 VCC | ESP32 5 V pin (VIN) | | 5 V power |
| HC-SR04 GND | common ground | | power |
| HC-SR04 Trig | J4-18 (J14) | | engine pin 8 (out only): the 10 us trigger pulse; 3.3 V is enough |
| HC-SR04 Echo | 1 k resistor | the other end to J4-8 (N16) and a 2 k resistor to GND | echo pulse (5 V) divided to 3.3 V, engine pin 1; 58 us per cm |

## 7. What is plugged in right now (4 Nov 2026, midday): no double booking

Every J4 hole, taken or free. A new program may only use a FREE hole; moving a lead means updating this table.

| J4 hole | Ball / engine pin | Now | |
|---|---|---|---|
| 1 | IO1, 3.3 V | TAKEN: the keypad's four 10 k pull-ups (and the I2C pull-ups if they are on the kit's rail) | |
| 2 | IO1, 3.3 V | TAKEN: the IR receiver's + lead (or it is on hole 1); the AT24C module's VCC (4 Nov night); the DS3231, MCP4725 and W25Q32 modules' VCC too when they are in (sections 11-13: a 3.3 V rail fed from hole 1 or 2 is tidier) | |
| 3, 4, 5, 7, 9 | K12, K13, M14, L14, M15 = CS, IRQ, MOSI, MISO, SCK | TAKEN: the host (the ESP32, or the Pico 2 while its leads are on: one at a time, section 8) | |
| 6 | N14, engine pin 0 | TAKEN: the serial line (the DALI RX will take it instead, section 10, planned). With the ESP32 as host, its GPIO 16 reads the chip's UART out. With the Pico as host (4 Nov night), **Pico GP0 (board pin 1, USB end, top left) sends to the chip** for `pico/uart_rx.py`; the ESP32 lead must be out of this hole then (an unpowered ESP32 clamps the line) | |
| 8 | N16, engine pin 1 | TAKEN: the KY-022 IR receiver's S lead (4 Nov afternoon); the HC-SR04 echo will need it, one at a time | |
| 10, 13 | M16, L15 = engine pins 2, 3 | TAKEN: I2C SCL and SDA, now to the AT24C256 module (section 9, 4 Nov night); the DS3231 module (0x57 and 0x68, section 12) and the MCP4725 DAC (0x60, section 13) join the same two wires from 5 Nov. Before that the UNO's A5 and A4 (`-Cmd n` PASS). The UNO answers at 0x50 too: not both | |
| 11, 12, 21, 22 | GND | ground | |
| 14, 15, 16, 17 | L16, K14, K16, K15 = engine pins 4-7 | TAKEN: keypad columns (tail 5-8); the 74HC595 is out of circuit since 4 Nov. **The W25Q32 flash (section 11) takes these same four holes**: the column leads come out for it, one at a time, as for the 595 | |
| 18, 20 | J14, J15 = engine pins 8, 10 (out only) | **FREE**: 18 is pencilled for the HC-SR04 trigger and for the DALI TX (section 10, planned), one at a time | |
| 19 | H14 = engine pin 9 (out only) | TAKEN: the IR emitter's signal lead (4 Nov evening) | |
| 23, 24, 25 | J16, H15, H16 = engine pins 11, 12, 13 (out only) | **FREE** | |
| 26 | G15, engine pin 15 | TAKEN: ESP32 GPIO 17 test pulses (the regression needs it) | |
| 27, 28, 29, 30 | G16, F15, F16, E15 = engine pins 16-19 | TAKEN: keypad rows (tail 1-4) with 10 k to hole 1 | |

ESP32 pins taken: 4, 5, 16, 17, 18, 19, 23 (host), 21 and 22 only if it is the I2C slave; VIN (5 V) is free for the HC-SR04.
Free engine pins for anything new: **8, 10-13** (out only, J4-18, 20 and 23..25). The two-way pins 0-7 are all spoken for
while the keypad and the IR receiver are on; a program needing a two-way pin means unplugging one of them. `spi_master.asm`
needs four consecutive pins with the third (MISO) able to read, which on this kit is pins 4-7 only (section 11).

## 8. Pico 2 as the host instead of the ESP32 (4 Nov 2026)

The Raspberry Pi Pico 2 (RP2350, MicroPython v1.29.0 from `D:\Tools\pico2_micropython`) does the ESP32's job over the same SPI host port,
as the Tiny Tapeout demo board's RP2040 will. **One host at a time**: move the five SPI/IRQ leads and the ground from the ESP32 to the Pico
(unplug them at the ESP32 end, plug into the Pico; the kit end stays put). The ESP32's other two leads (J4-6, J4-26) can stay: they are
not part of the host port.

| FROM | TO | What it is |
|---|---|---|
| J4-3 (K12) | Pico GP17 (pin 22) | CS |
| J4-5 (M14) | Pico GP19 (pin 25) | MOSI (the Pico's SPI0 TX) |
| J4-7 (L14) | Pico GP16 (pin 21) | MISO (SPI0 RX) |
| J4-9 (M15) | Pico GP18 (pin 24) | SCK |
| J4-4 (K13) | Pico GP20 (pin 26) | IRQ |
| J4-11 (GND) | Pico GND (pin 23, between GP18 and GP19) | common ground |

Pico pin numbers count from the USB-end top-left corner of the board, down the left side. Files: `pico/chip_host.py` (the host module),
`pico/programs.py` (the programs, generated by `python esp32/make_programs_h.py`), `pico/id_test.py`. Copy with
`pwsh D:\ProtocolASIC\pico\put.ps1 chip_host.py programs.py id_test.py`, run with `pwsh D:\ProtocolASIC\pico\run.ps1 -Script id_test.py`.
First test: the ID register must read 0x0022 five times.

## 9. AT24C256 EEPROM module on the I2C bus (4 Nov 2026, from the Pico)

A blue AT24C256 module (32 KB, 2 address bytes, 64-byte pages, labelled VCC SCL SDA GND on its right-hand pins, jumpers WP A0 A1 A2 on the
left, power LED D1) replaces the UNO test slave on J4-10 and J4-13 (the UNO also answers at 0x50, so it must be unplugged). Its own pull-ups go
to VCC, so **power it from 3.3 V only** (5 V would put 5 V on the FPGA's I2C pins). With A0-A2 jumpers to GND it answers at 0x50; WP to GND
= writes allowed.

| FROM | TO | What it is |
|---|---|---|
| module VCC | J4-2 (3.3 V) | power (the D1 LED lights) |
| module SCL | J4-10 (M16) | engine pin 2 |
| module SDA | J4-13 (L15) | engine pin 3 |
| module GND | the board's negative rail, **which must itself be wired to a kit GND hole (J4-11 or J4-12)** | ground: for a while the rail had no wire to the kit and only the logic analyser's ground lead tied it in (nothing answered, the LED was dim, until it was); fixed 4 Nov night by wiring the kit's GND to the rail |

Test: `pwsh D:/ProtocolASIC/pico/run.ps1 -Script at24c.py` (probe, read as found, page write, write cycle, sequential and random read, the top of the
memory for the 2-byte address, then everything put back). Edit ADDR_BYTES at the top for a part with 1 address byte.

## 10. DALI (planned 4 Nov 2026, NOT YET WIRED: the gear and the shield are on order)

The chip side is model-proven (`programs/dali_tx.asm`, `programs/dali_rx.asm`, `model/test_dali.py`); the run is
`pico/dali.py` from the Pico, the full note `docs/dali_bench.md`. Interface: the **Waveshare Pico-DALI2** shield (isolated,
polarity-free DALI terminal, no bus supply of its own; no Pico in it, jumper leads into its female header, pins numbered as a
Pico's). Bus supply: a DALI PSU, or 12-18 V DC through 56 ohm 2 W. The gear (a DALI LED driver) across the bus.
**Leads that move:** the Pico's GP0 UART lead comes out of J4-6; J4-18 is the HC-SR04 trigger's hole, one at a time.

| FROM | TO | AND | What it is |
|---|---|---|---|
| J4-18 (J14) | shield pin 9 (DALI TX) | | engine pin 8, out only: high = bus shorted, idle low |
| shield pin 5 (DALI RX) | J4-6 (N14) | | engine pin 0: bus high = 1, bus shorted = 0 (pins 15-19 have pull-downs in the kit build, so not those) |
| J4-1 or J4-2 (3.3 V) | shield pin 36 (3V3) | | logic-side power |
| J4-11 or J4-12 (GND) | shield pin 3 (or any GND pin) | | common ground; the bus side is isolated from it |
| shield DALI terminal | the gear's DA terminals | the bus supply (DALI PSU, or 12-18 V through 56 ohm 2 W) | the bus, any polarity |
| shield pin 4 | not connected | | the shield's bus-voltage sense |

Expected printout: DAPC 254 no answer, QUERY LEVEL 254, DAPC 127, QUERY LEVEL 127, DEVICE TYPE 6, STATUS with "lamp on",
OFF, QUERY LEVEL 0: PASS. If nothing comes back, `docs/dali_bench.md` has the order of checks (pin 0 with `read_pins.asm` first).

## 11. W25Q32 SPI flash module (parts due 5 Nov 2026, NOT YET RUN; `pico/w25q.py`)

Engine A runs `programs/spi_master.asm` (mode 0, MSB first, SCK 1 MHz) to a Winbond W25Q32 module (32 Mbit = 4 MB, 3.3 V).
**Why these holes:** the program takes its four pins as one group from `set_base`: SCK = base + 0, MOSI = base + 1,
MISO = base + 2 (the one input), CS = base + 3, and sets the directions itself, so the four must be consecutive engine pins with
the third able to read. On the kit that is engine pins 4-7 only: 8-13 are output only (a MISO there reads nothing), 15-19 input
only, pin 14 is not on the header, and 0-3 are the serial line, the IR receiver and I2C. So the flash takes the 74HC595's holes:
**the keypad's four column leads (tail 5-8) come out of J4-14 to 17 first**; the rows and their pull-ups can stay in.
Most modules pull WP and HOLD up on the board; if yours brings them out bare, tie both to 3.3 V (a low on either stops writes
or stalls the part).

| FROM | TO | AND | What it is |
|---|---|---|---|
| J4-14 (L16) | module CLK | | SCK, engine pin 4 |
| J4-15 (K14) | module DI (IO0) | | MOSI, engine pin 5 |
| J4-16 (K16) | module DO (IO1) | | MISO, engine pin 6: the flash's data back |
| J4-17 (K15) | module CS | | CS, engine pin 7 (idles high) |
| module VCC | J4-1 or J4-2 (3.3 V) | | power: 3.3 V only |
| module GND | the negative rail | rail wired to J4-11 or J4-12 | ground |
| module WP, HOLD | as the module has them (pulled up on board) | or to 3.3 V if bare | write protect and hold, both must be high |

Test: `pwsh D:/ProtocolASIC/pico/run.ps1 -Script w25q.py -Seconds 30`. Expected lines: JEDEC ID **EF 40 16** (Winbond, 4 MB;
other IDs are decoded), a unique ID read twice the same, status 1 = 00, 16 bytes at address 0 as found (FF on a new part), then the
write proof: the first all-FF 16-byte region from the top of memory down is page-programmed with a clock-seeded pattern, BUSY
polled (under 3 ms), read back equal, WEL cleared; address 0 unchanged: PASS. Each run uses one more 16-byte region of the top
4 KB sector (flash only clears bits); `ERASE = True` at the top of the script erases that sector (0x20, 50-400 ms), which wears the
part, so only when the regions run out. All 00 or all FF for the ID = a lead: CS and CLK (J4-17, 14), DO to J4-16, then power.

## 12. DS3231 clock module on the I2C bus (parts due 5 Nov 2026, NOT YET RUN; `pico/ds3231.py`)

The ZS-042-type module: a DS3231 at **0x68** and an AT24C32 EEPROM (4 KB, 2 address bytes, 32-byte pages) at **0x57** (its A0-A2
pads are pulled high), 4.7 k pull-ups to VCC on board, so **3.3 V only**. It joins the AT24C256 (0x50) on the same two wires: no
lead moves. At 3.3 V the module's LIR2032 charge path (VCC, diode, 200 ohm) sits below a 3 V cell and does nothing, so a plain
CR2032 is safe in it here. Two things in the drawer answer at 0x68 (this and the GY-521's MPU6050): the script reads register
0x75 (an MPU6050 answers 0x68 there, its WHO_AM_I) and proves the clock by its running seconds.

| FROM | TO | AND | What it is |
|---|---|---|---|
| module VCC | J4-1 or J4-2 (3.3 V) | | power: 3.3 V only |
| module GND | the negative rail | rail wired to J4-11 or J4-12 | ground |
| module SCL | J4-10 (M16) | the AT24C256 module's SCL stays | engine pin 2 |
| module SDA | J4-13 (L15) | the AT24C256 module's SDA stays | engine pin 3 |
| module 32K, SQW | not connected | | 32 kHz and square-wave outputs, unused |

Test: `pwsh D:/ProtocolASIC/pico/run.ps1 -Script ds3231.py -Seconds 20`. Expected lines: answered 0x50 0x57 0x68; register 0x75
not 0x68; the seven time registers, then again two seconds later with **seconds advanced by 2** (1-3 passes); 24-hour mode; the
temperature in degrees (the room, 10-35 C); the AT24C32 page write, read back, the top of the 4 KB (0x0FF0) written without
disturbing 0x0010 (the high address byte is used), everything put back: PASS. Status bit OSF set = the clock has stopped since it
was set (no battery): put a tuple in `SET_TIME` at the top of the script to set it.

## 13. MCP4725 DAC module on the I2C bus (parts due 5 Nov 2026, NOT YET RUN; `pico/mcp4725.py`)

A 12-bit DAC at **0x60** (or 0x61 with its A0 pad high; 0x62/0x63 on an A1 part: the script probes 0x60-0x67), on the same two wires,
the master at 400 kHz. Output = VDD x code / 4096, so with the 3.3 V supply 0, 1.65 and 3.30 V for codes 0, 2048 and 4095. Meter
the OUT pin against the rail; the scope on OUT for the ramps. Fast-mode writes (two bytes a value) leave the DAC's EEPROM alone.

| FROM | TO | AND | What it is |
|---|---|---|---|
| module VDD (VCC) | J4-1 or J4-2 (3.3 V) | | power: 3.3 V only; the output's full scale |
| module GND | the negative rail | rail wired to J4-11 or J4-12 | ground |
| module SCL | J4-10 (M16) | the other modules' SCL stay | engine pin 2 |
| module SDA | J4-13 (L15) | the other modules' SDA stay | engine pin 3 |
| module OUT | meter red lead / scope CH1 probe | black lead / probe ground to the rail | the DAC output |
| module A0 | as the module has it | | address low bit: open or low = 0x60 |

Test: `pwsh D:/ProtocolASIC/pico/run.ps1 -Script mcp4725.py -Seconds 40`. Expected: the address found; 0 V, 1.65 V, 3.30 V held
3 s each for the meter; a 64-step sawtooth for 10 s and a triangle for 10 s with every byte acked: PASS. The ramp frequency is
host-limited (each byte is a host round trip), so the script measures the ramps it made and prints the Hz the scope must show;
the wire itself would allow 18 bits a step = 347 Hz at 400 kHz. Scope: CH1 on OUT, 1 V/div, trigger on the sawtooth's falling flyback.

## 14. Mojo v3 with the IO Shield stacked, Pico as host (5 Nov 2026; regression PASS)

Three engines at 50 MHz (ID **0x0023**). Leads go into the IO Shield's stacking headers. Each header row has two holes and
**the number printed beside a hole is that hole's FPGA pin**: on the right header the inner hole (towards the display) is
labelled on the inside (50, 40, 34 ...) and the outer hole on the board edge (51, 41, 35 ...); on the left header the inner
hole is the higher number (58) and the outer the lower (57). Right header, from the USB end: row 1 inner RAW / outer GND,
row 2 inner +V / outer GND, then 50/51, 40/41, 34/35, 32/33, 29/30, 26/27 ... 133/134, 131/132, 126/127, 123/124. Left
header, from the USB end: inner GND, GND, VSYS, 58, 67, 75 ...; outer RAW, +V, DONE, 57, 66, 74 ... **All 24 shield DIP
switches OFF** (engine pins 15-19 are DIP switch pins). Load: `wsl -d Ubuntu -- bash /mnt/d/ProtocolASIC/fpga/mojo/build.sh load`
or `python fpga/mojo/load.py COM14 fpga/mojo/build/chip.bin` (FPGA RAM only). **The Mojo boots its flash design after any
power blip or reset button press**: the LEDs then fade and the ID reads garbage; reload.

| FROM (Pico) | TO (Mojo shield hole) | What it is |
|---|---|---|
| GND (pin 23) | right header row 1, **outer** hole, edge label GND (the inner hole is RAW) | common ground |
| GP17 (pin 22) | right header, inner hole **50** | CS |
| GP18 (pin 24) | right header, outer hole **51** | SCK |
| GP19 (pin 25) | right header, inner hole **40** | MOSI |
| GP16 (pin 21) | right header, outer hole **134** (4th row from the far end) | MISO (also the Mojo's LED0) |
| GP20 (pin 26) | right header, inner hole **133** (same row) | IRQ (also the Mojo's LED1) |
| GP1 (pin 2) | right header, outer hole **41** | engine pin 0: engine A's UART out into the Pico's UART0 RX |
| GP2 (pin 4) | left header, outer hole **57** (4th row) | engine pin 15: test pulses and levels from the Pico |

Every engine pin, for anything new (hole label = FPGA pin):

| Engine pins | Holes | Notes |
|---|---|---|
| 0-7 (two-way, pull-ups) | 41 (outer), 34 (inner), 35 (outer), 32 (inner), 33 (outer), 29 (inner), 30 (outer), 27 (outer) | right header; I2C SCL/SDA = 35/32; SPI SCK/MOSI/MISO/CS = 33/29/30/27 |
| 8-13 (out only) | 132 (outer), 131 (inner), 127 (outer), 126 (inner), 124 (outer), 123 (inner) | right header; the Mojo's LED2-LED7 light with them |
| 15-19 (in only, pull-downs) | 57 (outer), 58 (inner), 66 (outer), 67 (inner), 74 (outer) | left header; DIP switches OFF to use a lead |

**Serialiser build** (`build.sh ser`, two engines, ID 0x0022; `ser clk40` for 40 MHz): TD+ = engine pin 1, hole **34**
(inner), TD- = engine pin 2, hole **35** (outer), both in the row after 40/41. Logic analyser: CH1 -> 34, CH2 -> 35, GND ->
right header row 1 outer (GND). Tests: `-Script eth_tx.py -Pre "MODE='leads'"` (levels for checking the leads), then
`MODE='eth'`, `MODE='dali'`, and with the 40 MHz build `MODE='full'; CHIP_HZ=40_000_000`; captures decoded with
`python docs/bench/decode_manchester.py file.sr [--mode dali]`.

Shield LEDs: one bank shows engine pins 0-7 as the pads read, one which of 0-7 an engine drives, the third pins 15-19, host
CS active, reset held and a heartbeat (`fpga/mojo/chip_mojo.v`). Tests: `pwsh D:/ProtocolASIC/pico/run.ps1 -Script id_test.py`
(0x0023 five times), then `-Script regression.py -Seconds 40` (CHIP_HZ = 50_000_000 at the top): PASS, 0 problems.
If it doesn't answer: `-Script lead_probe.py` (MISO and IRQ driven and steady with CS idle; toggling = the flash design is
running), then `TOP=pin_finder` build of `fpga/mojo/pin_finder.v` (touch a hole with a ground lead through 220 R - 1 k: the
display shows P and the pin number).

## If it doesn't answer: bench helpers (`esp32
erun.ps1 -Cmd <letter>`)

| Command | Does | Tells you |
|---|---|---|
| `p` | lead probe: reads MISO and IRQ with the ESP32's pull-up then pull-down, then one raw ID read | a FLOATING pin = that lead open or in the wrong hole; ID 0x0000 with MISO driven = CS, SCK or MOSI not arriving; 0xFFFF = MISO open |
| `q` | engine B keeps data waiting for 15 s, GPIO 4 polled | the IRQ lead (and the kit's IRQ LED P16) |
| `b` | I2C wire check: engine B reads all 20 engine pins while the ESP32 pulls its SDA, then its SCL, low | the chip pin each I2C lead actually reaches (expect SDA = pin 3, SCL = pin 2); nothing moving = that lead is in a hole the chip cannot read (3 Nov: H16, hole 25, read as M16) |
| `k` | GPIO 22 (the ESP32's SCL) held low for 30 s | time to meter both ends of the SCL lead |
| `l` | ID reads over and over for 30 s | a repeating burst on CS, SCK, MOSI and MISO for the oscilloscope; MISO should read 0x0022 |
| `y` | keypad: names every key pressed until any character is sent | section 6 wiring; a key that never shows = its row or column lead; every key mirrored = the tail numbered the other way; every key "pressed" (map FFFF, or 5555 / AAAA) = those rows' pull-ups not reaching J4-27..30 (an open input-only hole reads low: the kit build gives pins 15-19 internal pull-downs) |
| `e` | live level of engine pins 15-19 (J4-26..30) for 30 s, a line on every change | wiggle a lead or touch a jumper from 3.3 V to a hole while it runs; a row with its 10 k in place must read 1, and its resistor shows about 0.5 V drop (the internal pull-down's 50 uA); no drop = that row is open |

Lesson of 4 Nov night: **an instrument on the bus is powered or unclipped, never off and attached.** The logic analyser switched off with
its probes still on SCL and SDA clamped both lines through its input diodes: the EEPROM NAKed its address, writes failed, reads came
back FD FD FD FD, while the chip's own sniffer showed the bus faithfully. Powered on, everything passed again.

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
