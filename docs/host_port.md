# Host port, v0.3

v0.2 plus the serialiser and CRC registers 0x2B-0x33 and two STATUS bits; the receive and full-duplex registers
(0x34-0x37, SERCFG `[9:7]`) are marked v0.4, as in `docs/isa.md`.

How a microcontroller (the RP2350 on the Tiny Tapeout demo board, an ESP32, a Raspberry Pi) talks to the chip.
The Tiny Tapeout chip has **four engines** (A-D, numbered 0-3); the FPGA builds have one to three
(`docs/core_design.md`, "Builds"). Read register 0x2A to find out how many.

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
edge and the next falling edge. (A host that samples late in the bit, as the ESP32's SPI hardware does, still reads
the right bit; the whole-chip test checks both with `LATE=1`.)
The chip samples SCK with its own clock, so **SCK must be at most 1/8 of the chip clock**
(e.g. 6 MHz SPI for a 50 MHz chip). This keeps the whole chip in one clock domain: no crossing hazards.

## A transaction

```
CS low | 16-bit command | 16-bit word | 16-bit word | ... | CS high
```

Command: `[15] 1 = read, 0 = write`  `[14:12] engine (0 = A, 1 = B, 2 = C, 3 = D)`  `[11:6] cluster (0)`  `[5:0] register`.
So the first byte is `read << 7 | engine << 4` and the second is the register. An engine number past the last one is
harmless: its writes are ignored and its reads return 0.

Bits `[11:6]` are the **cluster number** (`docs/core_design.md`, Hierarchy). This chip has one cluster,
number 0, which holds all its engines and the chip-wide registers. A cluster number that does not exist (1 to 63 here)
reads 0 for every register, FILTER and ID included, and its writes are ignored. Hosts send 0 in these bits.

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
| 0x26 | TXFIFO | W (R) | push a word to the engine (dropped if the FIFO is full: check STATUS). Engine 0's FIFO holds 1024 words (64 on the FPGA serialiser builds), the others 4. **Engine 0 in receive mode:** reads take the received words in order (0 when none); writes are dropped |
| 0x27 | RXFIFO | R | pop a word from the engine (reads 0 if empty) |
| 0x28 | STATUS | R | [2:0] TX level **saturating at 7** (the exact level is in 0x33), [6:4] RX level, [8] running, [13:9] pc, [14] serialiser busy, [15] serialiser underrun (engines 1-3: 0) |
| 0x29 | FILTER | R/W | **chip-wide** (any engine number reaches it): input glitch filter, [3:0] N, [7:4] P; a new input level must hold for N+1 ticks of 2^P clocks (docs/input_filter.md). 0 = shortest (about 1 clock) |
| 0x2A | ID | R | **chip-wide**: [3:0] number of engines (4 on the Tiny Tapeout chip; FPGA builds 1-3), [7:4] this spec's version (2) |
| 0x2B | SERCFG | R/W | **engine 0 only** (reads 0 and ignores writes on the others): [0] serialiser enable, [1] Manchester (else NRZ), [2] differential (out_base + 1 carries the inverse), [3] end marker (line high 6 half-bits after the last bit), [4] CRC append (32 bits after the data), [5] complement the appended CRC, [6] CRC watches the serialiser's bits (else IN bits), [8:7] mode (v0.4: read back the mode in force, 00 transmit, 01 receive, 10 full duplex; a write changes it only with the key 101 in [15:13], [8] = 1 asking for full duplex, else [7]; only when idle; see docs/isa.md "Receiver and full duplex"), [9] hardware preamble (seven 0x55 and the SFD before each frame), [12:10] CRC skip: the first N words of a frame are not fed to the CRC (4 for Ethernet's preamble and SFD) |
| 0x2C | SERDIV | R/W | **engine 0 only**: half-bit period in chip clocks, minus 1 (10 Mbit Manchester: 0 at 20 MHz, 1 at 40 MHz) |
| 0x2D, 0x2E | CRCPOLY lo, hi | R/W | the CRC unit's polynomial, reflected form (Ethernet 0xEDB88320, Modbus 0xA001) |
| 0x2F, 0x30 | CRCINIT lo, hi | R/W | the CRC unit's start value (Ethernet 0xFFFFFFFF, Modbus 0xFFFF) |
| 0x31, 0x32 | CRC lo, hi | R | the CRC register now (the running value, not complemented) |
| 0x33 | SERSTAT | R | [6:0] TX FIFO level **saturating at 127** (the exact level is in 0x38), [8] serialiser busy, [9] serialiser underrun |
| 0x34 | RXCFG | R/W | **engine 0 only** (v0.4): [4:0] receive pin, [5] raw (no preamble hunt), [6] sample on both clock edges; writing [7] = 1 arms the receiver for one frame (empties the buffer; [7] is not kept) |
| 0x35 | RXGAP | R/W | **engine 0 only**: 3/4 of a bit in half-clocks (reset 6: 10 Mbit/s at 40 MHz); no edge for twice this ends a frame |
| 0x36 | RXSTAT | R | **engine 0 only**: [0] frame ready, [1] overrun, [2] in a frame (locked), [3] refused (a mode change or MOV ser was refused), [7:4] bits in a partial last word, [14:8] words received **saturating at 127** (the exact count is in 0x39), [15] the receiver on (receive or full duplex) |
| 0x37 | RXDATA | R | **engine 0 only**: in receive or full duplex, reads take the received words in order (0 when none) |
| 0x38 | SERLEVEL | R | [10:0] the TX FIFO level, exact (0-1024; in full duplex the transmit ring's, 0-512) |
| 0x39 | RXWORDS | R | **engine 0 only**: [10:0] words received this frame, exact (reads 0 on the other engines) |

Unlisted registers read 0 and ignore writes. Registers 0x2B-0x30 are settings like 0x21-0x25: change them while the
engine is stopped. The serialiser (docs/isa.md, "Serialiser") is started by the program, not the host: the host pushes
a word count and then that many words into engine 0's TX FIFO, in one burst, and the program does `pull block` then
`mov ser, osr`; the serialiser waits until the FIFO holds the whole count before the first bit goes out.
`programs/eth_tx.asm` is the Ethernet case.

Receive (v0.4, engine 0): with the engine running, set MISC `in_right` for LSB-first data, RXGAP for the rate, then write SERCFG with the key and bit 7 set (`sercfg | 0xA080`) and read SERCFG back to see receive in force.
Write RXCFG with the pin, bit 6 and the arm bit; when RXSTAT bit 0 (or IRQ) rises, read RXWORDS (0x39) words from 0x26.
Arm again for the next frame. `sercfg | 0xA000` returns to transmit once idle. The IRQ pin also rises while a received
frame is ready. The receiver bypasses the glitch filter, so FILTER can stay set for the other pins.

Full duplex (v0.4, engine 0): `sercfg | 0xA100` (with `[9]` set for the hardware preamble), read SERCFG [8:7] back as
10, arm with RXCFG as above. Send as in transmit mode, but the transmit ring holds 512 words (16 on the 64-word builds): push
while SERLEVEL is under that (a longer frame starts when the ring is full and must be topped up as it goes). Read received words from
0x37.

Builds without the serialiser (the default FPGA builds: `SER0 = 0`, 4-word TX FIFOs; `docs/core_design.md`, "Builds")
read 0 at 0x2B, 0x2C, 0x34-0x37 and 0x39 and have STATUS bits 14-15 at 0 (SERSTAT still gives the TX FIFO level). Builds without CRC units (`CRC = 0`, the Tiny Tapeout chip
among them) read 0 at 0x2D-0x32. The ID register's layout is the same in every build. All settings reset to 0 (engines stopped) when the chip resets.
Change settings while an engine is stopped; they are applied when RUN goes to 1.

## Engine pins to chip pins

Each engine sees 32 pin numbers. On this chip:

| Engine pin | Chip pin | Can |
|---|---|---|
| 0-7 | `uio[0..7]` | in and out (open-drain style use for I2C: direction 0 = let go) |
| 8-13 | `uo_out[2..7]` | out only (drives only while an engine sets its direction to 1; reads back as 0) |
| 15-19 | `ui_in[3..7]` | in only |
| others | none | read as 0 |

If several engines drive the same pin, the lowest-numbered one wins (A over B over C over D). Every engine can read every input.
Every input (engine pins 0-7 and 15-19) passes through a 2 flip-flop synchroniser and the glitch filter
before the engines see it, which adds a few clocks of delay (the same on rising and falling edges).
