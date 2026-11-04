# DALI on the bench (planned 4 Nov 2026, not yet wired: the gear is on order)

The chip side is done and model-proven (`programs/dali_tx.asm`, `programs/dali_rx.asm`, `model/test_dali.py`); this note is
the interface Mark will build and the scripted run (`pico/dali.py`) for when the parts arrive. Everything here is marked
**planned, not yet wired** until a bench pass is read back line by line.

## What DALI is, in chip terms

One pair of wires, polarity-free, 16 V nominal (9.5 to 22.5 V) from a current-limited supply (250 mA max). Idle is
**bus high**; a transmitter talks by **shorting the bus** (a transistor across it). 1200 bit/s Manchester: a bit is 833 us
in two halves; a 1 is low then high, a 0 high then low. A forward frame (controller to gear) is a start bit (a 1), 16 bits MSB
first (address byte, then command or level byte), then idle. The gear answers a query with a backward frame of 8 bits,
starting 2.9 to 9.2 ms after the forward frame ends; silence means "no" (or nobody there). The next forward frame waits
9.17 ms. So the chip needs one output pin to drive the shorting transistor and one input pin to read the bus level: the
one-wire end of the bus ladder in `docs/bus_variants.md`, where the engine does all the timing.

## The interface: Waveshare Pico-DALI2 (decided 4 Nov 2026)

An isolated DALI board on the Pico footprint (SKU 28643, about 5.50 USD): two optocouplers and a bridge rectifier, so the
bus side is isolated and polarity-free, and it has **no bus supply** of its own. No Pico sits in it: jumper leads go into
its female 40-pin header, numbered as a Pico's physical pins.

| Shield header pin | Signal | Wire to | What it is |
|---|---|---|---|
| 36 | 3V3 in | kit J4-1 or J4-2 (3.3 V) | power for the logic side |
| 3 (or 8, 13, 18, 23, 28, 33, 38) | GND | kit J4-11 or J4-12 | common ground |
| 9 | DALI TX (input) | kit **J4-18 (J14)**, engine pin 8, out only | pin HIGH = bus shorted, idle LOW |
| 5 | DALI RX (output) | kit **J4-6 (N14)**, engine pin 0 | 3.3 V logic, bus high = 1, bus shorted = 0 |
| 4 | bus voltage sense (divided) | not connected | |
| DALI terminal | the bus | the gear's DA/DA terminals and the bus supply, any polarity | |

Polarity is exactly what the programs assume: TX pin high shorts the bus, RX reads the bus level without inversion. (Verified
from Tasmota's driver for this shield: its "TX_i" pin idles low and goes high to pull the bus down; RX is plain.)

**Bus supply.** Either a DALI PSU (any "DALI PS" or a driver with a built-in bus supply) or a 12 to 18 V DC wall supply through
**56 ohm 2 W** in series (that is the DALI current limit, about 250 mA into a short, and the resistor takes 3.5 W for the
instants the bus is shorted, under 2 W on average: a 2 W part is fine, a 5 W one cooler). The supply's negative goes to the
bus, not to the kit: the shield is isolated, so the bus has no connection to the kit's ground at all.

**Gear.** Any "DALI dimmable" LED driver (Mean Well LCM-xxDA or similar, 15 to 25 GBP) with a load on it, its DA terminals
across the bus. Out of the box it has no short address, which is why the script uses broadcast only.

**Leads that move.** J4-6 normally carries the Pico's GP0 UART lead for `pico/uart_rx.py`: out for DALI. J4-18 is free
(pencilled for the HC-SR04 trigger: one at a time). Nothing else changes; the Pico stays the host on holes 3, 4, 5, 7, 9, 11.

**Why engine pin 0 for RX and not an input-only pin.** The kit build gives pins 15-19 (J4-26 to 30) weak pull-downs, which would
load any divider or a weak output; pins 0-7 have pull-ups, harmless on a driven 3.3 V output. On the real chip either kind
of pin works (no pulls); `pico/dali.py` has `RX_PIN` at the top.

## Fallback: a hand-built interface (if the shield is not to hand)

Not isolated: the bus negative becomes the kit's ground, so the bus supply must float (a wall supply, not the bench PSU
if that is earthed). Bus supply 12 to 18 V DC through 56 ohm 2 W. **Transmit:** an NPN (BC337 or any 500 mA part) emitter
to bus minus, collector to bus plus, base through **1 k** from J4-18: engine pin 8 high turns it on and shorts the bus,
which is the same polarity as the shield. (A MOSFET module or an opto with its output pulled up to the bus inverts: the
header of `dali_tx.asm` lists the four pin writes to swap.) **Receive:** bus plus through **47 k** to J4-6, **10 k** from J4-6 to
ground (16 V bus reads 2.8 V, 12 V reads 2.1 V, both above the 2.0 V input threshold), and a **3.3 V zener** (or a Schottky
to J4-1) across the 10 k as the clamp for a 22.5 V bus or a spike. Bus minus to J4-11.

## The scripted run

```
pwsh D:\ProtocolASIC\pico\put.ps1 chip_host.py programs.py dali.py
pwsh D:\ProtocolASIC\pico\run.ps1 -Script dali.py
```

Both engines run at clkdiv 1249 (a tick of 104.17 us, an eighth of a bit). Engine A's program holds the bus idle 9.5 ms
after every frame, so frames can be queued. For every frame the script first arms B with the listening window (96 ticks
= 10 ms), then pushes the frame to A; B skips the forward frame on the bus, waits for the bus to be quiet, then listens
10 ms for the gear's start bit and pushes one word: `0x100 | byte` (an answer), `0x000` (no answer), `0x200 | bits` (a
framing error: a mid-bit edge did not come). The lines, in order, with the answers expected:

| Sent | Word | Expect |
|---|---|---|
| broadcast DAPC 254 | FEFE | no answer |
| QUERY ACTUAL LEVEL | FFA0 | 254 |
| broadcast DAPC 127 | FE7F | no answer |
| QUERY ACTUAL LEVEL | FFA0 | 127 |
| QUERY DEVICE TYPE | FF99 | 6 (LED) |
| QUERY STATUS | FF90 | a frame with "lamp on" set; the other bits printed by name |
| OFF | FF00 | no answer |
| QUERY ACTUAL LEVEL | FFA0 | 0 |

PASS only if every line matches. The lamp itself should go full, half, off.

## If it does not answer

Continuity to the labelled holes first, as always. Then, in order:

1. Every line "NOTHING": engine B never pushed. B not running, or the window never ended: B is waiting at `wait 0` for a
   forward frame it never saw, so its RX lead (shield 5 to J4-6) or the shield's 3V3 is the suspect. `programs/read_pins.asm`
   shows pin 0: it must read 1 with the bus up and 0 with the bus shorted (short the DALI terminal with a lead).
2. Every line "no answer" but the lamp follows DAPC/OFF: the forward frames arrive, the answers do not reach pin 0, or come
   outside the 10 ms window. Scope the bus (the Hantek, 10x probe across the DALI terminal, 5 V/div, 5 ms/div, trigger on
   the first falling edge): the answer should start 2.9 to 9.2 ms after the frame.
3. The lamp does nothing: the TX side. With A stopped, J4-18 is driven low (bus released); `programs/drive_high.asm` on pin 8
   must short the bus (the bus voltage drops to a volt or two, the 56 ohm warms).
4. Framing errors: the gear's timing, or noise. The bits-so-far value says how far each frame got; the model test shows the
   receiver copes with a gear 10 % off, so a consistent failure at the same bit is worth a scope picture.
