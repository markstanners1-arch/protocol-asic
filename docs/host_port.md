# Host port, v0.3 (5 Nov 2026: v0.2 plus the serialiser and CRC registers 0x2B-0x33, two STATUS bits)

How a microcontroller (the RP2040 on the Tiny Tapeout board, an ESP32, a Raspberry Pi) talks to the chip.
The chip has **three engines** (A-C, numbered 0-2; four did not place on the tile); the MachXO3L bench build has two.
Read register 0x2A to find out how many.

## Wires

| Chip pin | Signal | Direction |
|---|---|---|
| `ui_in[0]` | CS (active low) | in |
| `ui_in[1]` | SCK | in |
| `ui_in[2]` | MOSI | in |
| `uo_out[0]` | MISO | out |
| `uo_out[1]` | IRQ: high while any engine's RX FIFO holds data | out |

SPI **mode 0** (clock idles low, data sampled on the rising edge, changed on the falling edge), MSB first.
MISO only ever changes just after a **falling** edge, so a host may sample it anywhere between the rising
edge and the next falling edge. (The ESP32 samples late; see the bench notes in the README.)
The chip samples SCK with its own clock, so **SCK must be at most 1/8 of the chip clock**
(e.g. 6 MHz SPI for a 50 MHz chip). This keeps the whole chip in one clock domain: no crossing hazards.

## A transaction

```
CS low | 16-bit command | 16-bit word | 16-bit word | ... | CS high
```

Command: `[15] 1 = read, 0 = write`  `[14:12] engine (0 = A, 1 = B, 2 = C)`  `[11:6] cluster (0)`  `[5:0] register`.
So the first byte is `read << 7 | engine << 4` and the second is the register. (v0.1 had a one-byte command with a
one-bit engine field; it grew on 3 Nov 2026 when the chip went from two engines to three.) An engine number past the
last one is harmless: its writes are ignored and its reads return 0.

Bits `[11:6]` are the **cluster number** (5 Nov 2026; `docs/core_design.md`, Hierarchy). This chip has one cluster,
number 0, which holds all its engines and the chip-wide registers. A cluster number that does not exist (1 to 63 here)
reads 0 for every register, FILTER and ID included, and its writes are ignored. Hosts that send 0 in these bits, as
every program so far does, see no difference.

Each 16-bit word is written to, or read from, the register; then the register number **moves on by one**,
except for the two FIFO registers, which stay put (so a burst of words goes through the same FIFO).
A whole program is loaded with one command and 32 words. When reading, the chip sends each word
while the host clocks out anything (zeros).

## Registers (per engine)

| Reg | Name | R/W | Contents |
|---|---|---|---|
| 0x00-0x1F | PROG[0..31] | W | program memory; written only while the engine is stopped (ignored when running) |
| 0x20 | CTRL | R/W | bit 0: RUN (1 = run, 0 = stopped and held in reset) |
| 0x21 | CLKDIV | R/W | 16 bits |
| 0x22 | WRAP | R/W | [4:0] start, [9:5] wrap_bottom, [14:10] wrap_top |
| 0x23 | OUTCFG | R/W | [4:0] out_base, [9:5] out_count (0-16), [14:10] set_base |
| 0x24 | MISC | R/W | [2:0] set_count, [7:3] side_base, [9:8] side_count, [10] side_opt, [11] out_right, [12] in_right, [13] side_dir (side-set writes pin directions) |
| 0x25 | INCFG | R/W | [4:0] in_base, [9:5] jmp_pin, [14:10] fault_addr |
| 0x26 | TXFIFO | W | push a word to the engine (dropped if the FIFO is full: check STATUS). Engine 0's FIFO holds 64 words, the others 4 |
| 0x27 | RXFIFO | R | pop a word from the engine (reads 0 if empty) |
| 0x28 | STATUS | R | [2:0] TX level **saturating at 7** (the exact level is in 0x33), [6:4] RX level, [8] running, [13:9] pc, [14] serialiser busy, [15] serialiser underrun (engines 1 and 2: 0) |
| 0x29 | FILTER | R/W | **chip-wide** (any engine number reaches it): input glitch filter, [3:0] N, [7:4] P; a new input level must hold for N+1 ticks of 2^P clocks (docs/input_filter.md). 0 = shortest (about 1 clock) |
| 0x2A | ID | R | **chip-wide**: [3:0] number of engines (3 on the chip, 2 on the kit), [7:4] this spec's version (2) |
| 0x2B | SERCFG | R/W | **engine 0 only** (reads 0 and ignores writes on the others): [0] serialiser enable, [1] Manchester (else NRZ), [2] differential (out_base + 1 carries the inverse), [3] end marker (line high 6 half-bits after the last bit), [4] CRC append (32 bits after the data), [5] complement the appended CRC, [6] CRC watches the serialiser's bits (else IN bits), [9:7] reserved, [12:10] CRC skip: the first N words of a frame are not fed to the CRC (4 for Ethernet's preamble and SFD) |
| 0x2C | SERDIV | R/W | **engine 0 only**: half-bit period in chip clocks, minus 1 (10 Mbit Manchester: 0 at 20 MHz, 1 at 40 MHz) |
| 0x2D, 0x2E | CRCPOLY lo, hi | R/W | the CRC unit's polynomial, reflected form (Ethernet 0xEDB88320, Modbus 0xA001) |
| 0x2F, 0x30 | CRCINIT lo, hi | R/W | the CRC unit's start value (Ethernet 0xFFFFFFFF, Modbus 0xFFFF) |
| 0x31, 0x32 | CRC lo, hi | R | the CRC register now (the running value, not complemented) |
| 0x33 | SERSTAT | R | [6:0] TX FIFO level (0-64), [8] serialiser busy, [9] serialiser underrun |

Unlisted registers read 0 and ignore writes. Registers 0x2B-0x30 are settings like 0x21-0x25: change them while the
engine is stopped. The serialiser (docs/isa.md, "Serialiser") is started by the program, not the host: the host pushes
a word count and then that many words into engine 0's TX FIFO, in one burst, and the program does `pull block` then
`mov ser, osr`; the serialiser waits until the FIFO holds the whole count before the first bit goes out.
`programs/eth_tx.asm` is the Ethernet case.

FPGA builds: the MachXO3L kit and the Cyclone IV board are built without the serialiser and the CRC units
(`SER0 = 0`, `CRC = 0`, 4-word TX FIFOs; `docs/core_design.md`), so on them 0x2B-0x32 read 0 and STATUS bits 14-15
are 0. The ID register is the same in every build. All settings reset to 0 (engines stopped) when the chip resets.
Change settings while an engine is stopped; they are applied when RUN goes to 1.

## Engine pins to chip pins

Each engine sees 32 pin numbers. On this chip:

| Engine pin | Chip pin | Can |
|---|---|---|
| 0-7 | `uio[0..7]` | in and out (open-drain style use for I2C: direction 0 = let go) |
| 8-13 | `uo_out[2..7]` | out only (drives only while an engine sets its direction to 1; reads back as 0) |
| 15-19 | `ui_in[3..7]` | in only |
| others | none | read as 0 |

If several engines drive the same pin, the lowest-numbered one wins (A over B over C). Every engine can read every input.
Every input (engine pins 0-7 and 15-19) passes through a 2 flip-flop synchroniser and the glitch filter
before the engines see it, which adds a few clocks of delay (the same on rising and falling edges).
