# Host port, v0.1 (2 Nov 2026)

How a microcontroller (the RP2040 on the Tiny Tapeout board, an ESP32, a Raspberry Pi) talks to the chip.

## Wires

| Chip pin | Signal | Direction |
|---|---|---|
| `ui_in[0]` | CS (active low) | in |
| `ui_in[1]` | SCK | in |
| `ui_in[2]` | MOSI | in |
| `uo_out[0]` | MISO | out |
| `uo_out[1]` | IRQ: high while either engine's RX FIFO holds data | out |

SPI **mode 0** (clock idles low, data sampled on the rising edge, changed on the falling edge), MSB first.
MISO only ever changes just after a **falling** edge, so a host may sample it anywhere between the rising
edge and the next falling edge. (The ESP32 samples late; see the bench notes in the README.)
The chip samples SCK with its own clock, so **SCK must be at most 1/8 of the chip clock**
(e.g. 6 MHz SPI for a 50 MHz chip). This keeps the whole chip in one clock domain: no crossing hazards.

## A transaction

```
CS low | command byte | 16-bit word | 16-bit word | ... | CS high
```

Command byte: `[7] 1 = read, 0 = write`  `[6] engine (0 = A, 1 = B)`  `[5:0] register`.

Each 16-bit word is written to, or read from, the register; then the register number **moves on by one**,
except for the two FIFO registers, which stay put (so a burst of words goes through the same FIFO).
A whole program is loaded with one command byte and 32 words. When reading, the chip sends each word
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
| 0x26 | TXFIFO | W | push a word to the engine (dropped if the FIFO is full: check STATUS) |
| 0x27 | RXFIFO | R | pop a word from the engine (reads 0 if empty) |
| 0x28 | STATUS | R | [2:0] TX level, [6:4] RX level, [8] running, [13:9] pc |
| 0x29 | FILTER | R/W | **chip-wide** (either engine-select bit reaches it): input glitch filter, [3:0] N, [7:4] P; a new input level must hold for N+1 ticks of 2^P clocks (docs/input_filter.md). 0 = shortest (about 1 clock) |

Unlisted registers read 0 and ignore writes. All settings reset to 0 (engines stopped) when the chip resets.
Change settings while an engine is stopped; they are applied when RUN goes to 1.

## Engine pins to chip pins

Each engine sees 32 pin numbers. On this chip:

| Engine pin | Chip pin | Can |
|---|---|---|
| 0-7 | `uio[0..7]` | in and out (open-drain style use for I2C: direction 0 = let go) |
| 8-13 | `uo_out[2..7]` | out only (drives only while an engine sets its direction to 1; reads back as 0) |
| 15-19 | `ui_in[3..7]` | in only |
| others | none | read as 0 |

If both engines drive the same pin, engine A wins. Both engines can read every input.
Every input (engine pins 0-7 and 15-19) passes through a 2 flip-flop synchroniser and the glitch filter
before the engines see it, which adds a few clocks of delay (the same on rising and falling edges).
