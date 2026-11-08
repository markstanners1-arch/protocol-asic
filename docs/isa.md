# Engine instruction set, v0.3 (5 Nov 2026: v0.2 plus the serialiser, the CRC unit and a 64-word TX FIFO on engine 0)

The exact rules. The Python model (`model/engine.py`) and the Verilog are both built from
this page, so if they disagree, this page says which one is wrong. Change it here first.

## State of one engine

| Name | Bits | Notes |
|---|---|---|
| `pc` | 5 | program counter into this engine's own 32-word program memory |
| `x`, `y` | 16 each | scratch / loop counters |
| `osr`, `osr_count` | 16, 0-16 | output shift register; `osr_count` = bits already shifted out (16 = empty) |
| `isr`, `isr_count` | 16, 0-16 | input shift register; `isr_count` = bits shifted in |
| `delay` | 5 | extra ticks still to wait after the current instruction |
| `sw`, `sw_run` | 16, 1 | stopwatch count and its run flag |
| `div` | 16 | clock divider count |
| `out_val`, `out_dir` | 32 each | the engine's pin output levels and directions (1 = drive) |
| TX FIFO, RX FIFO | 4 x 16 each | to and from the host; **engine 0's TX FIFO is 64 x 16** |
| `crc` | 32 | the CRC unit's register (every engine) |
| serialiser | | engine 0 only: `ser_busy`, `ser_under`, phase, word count, shift register, bit and half-bit counters, divider, skip counter (section "Serialiser") |

Reset: everything 0, except `osr_count = 16` (empty), `pc = start` and `crc = crcinit`.

## Configuration (written by the host, fixed while running)

| Name | Bits | Meaning |
|---|---|---|
| `clkdiv` | 16 | the engine ticks once every `clkdiv + 1` system clocks |
| `start` | 5 | first instruction after reset |
| `wrap_bottom`, `wrap_top` | 5, 5 | after executing the instruction at `wrap_top` (and not jumping), go to `wrap_bottom` |
| `out_base`, `out_count` | 5, 0-16 | pins written by `OUT pins` / `MOV pins`: `out_base` upwards |
| `set_base`, `set_count` | 5, 0-5 | pins written by `SET pins` |
| `side_base`, `side_count` | 5, 0-2 | side-set pins; `side_count` bits are taken from the top of the delay field |
| `side_opt` | 1 | if 1, the top bit of the middle field is a side-set **enable**, so instructions without `side N` leave the side pins alone |
| `side_dir` | 1 | if 1, side-set writes the side pins' **directions** instead of their levels (open-drain buses: a side value of 1 pulls the pin low, 0 lets it go). Added 2 Nov 2026 for I2C's SCL |
| `in_base` | 5 | `IN pins` reads from here upwards; `WAIT` relative pins count from here |
| `jmp_pin` | 5 | pin tested by `JMP PIN` |
| `out_right`, `in_right` | 1, 1 | shift direction: 1 = right (LSB first, UART), 0 = left (MSB first, SPI/I2C) |
| `fault_addr` | 5 | where a timed-out `WAIT` jumps to |
| `crcpoly`, `crcinit` | 32, 32 | the CRC unit's polynomial (reflected form) and start value (host registers CRCPOLY, CRCINIT) |
| SERCFG | 13 | engine 0 only: `[0]` enable, `[1]` Manchester, `[2]` differential, `[3]` end marker, `[4]` CRC append, `[5]` complement on append, `[6]` CRC watches SER, `[9:7]` reserved, `[12:10]` CRC skip words. Engines 1 and 2 have it fixed at 0 |
| `serdiv` | 16 | engine 0 only: the serialiser's half-bit period in system clocks, minus 1 |

Pin numbers wrap modulo 32 (a 32-pin space; the chip uses 20 of them).

## Instruction word

```
 15 14 13 | 12 11 10 9 8 | 7 6 5 4 3 2 1 0
  opcode  | side + delay  |   arguments
```

The 5-bit middle field, from the top: the enable bit (only if `side_opt`), then `side_count` bits of
side-set value, then the delay in whatever is left. E.g. `side_opt = 1, side_count = 1` leaves 3 bits of delay (0-7).

## Timing rules

- The engine does one step per **tick** (one tick every `clkdiv + 1` system clocks).
- If `delay > 0`, the step just counts it down.
- Otherwise it executes the instruction at `pc`. Side-set pins take their value on this step,
  **even if the instruction then stalls**.
  If the instruction and the side-set write the same pin (level, or direction when `side_dir`), the side-set wins.
- A stalled instruction (WAIT not met, PULL on an empty FIFO, PUSH on a full one) is tried again next tick.
  Its delay starts only once it completes.
- On completion: `delay` = the delay field; `pc` moves on (jump target, or `wrap_bottom` if `pc == wrap_top`, else `pc + 1` mod 32).
- The stopwatch, if running, counts every tick, stalls and delays included.
- Inputs pass through a **2-flip-flop synchroniser**: the engine sees each pin as it was 2 system clocks ago.
  The synchroniser resets to 0, so for the first 2 clocks after reset every pin reads low.
  Programs that look for a falling edge should first `wait 1` for the idle level (found by `model/test_measure.py`).

## Program memory (SRAM-ready, decided 2 Nov 2026)

The program memory behaves like IHP's SRAM block whichever cells build it: one port, reads on the clock.
- Every clock, the engine presents the address of the instruction it will need next (the next `pc`);
  the word arrives just after the clock edge, in time for the next step. While held in reset it reads `start`.
  So instruction timing is exactly as described below: the clocked read is invisible to programs.
- **Programs are written only while the engine is stopped (held in reset)**, and the engine must stay
  stopped for at least one clock after the last write, so the first instruction can be read.
- Built either from flip-flops (`prog_mem.v`, default) or from IHP's `RM_IHPSG13_1P_64x16_c2`
  (`+define+USE_SRAM`; uses 32 of its 64 words). Both are checked against the model.

## Host and FIFO timing

Within one system clock, everything is decided from the state at the **start** of that clock:
- The host's push into the TX FIFO is accepted only if the FIFO was not full at the start of the clock.
  On engines 1 and 2 the word becomes visible to the engine from the next clock; on engine 0, see below.
- The host's pop from the RX FIFO is accepted only if it was not empty at the start of the clock;
  the host gets the word that was at the head.
- The engine's PULL / PUSH and `MOV status` see the FIFO levels at the start of the clock, and so does the serialiser.
- So an engine PULL and a host push in the same clock both happen (count -1 +1), and so do an engine PUSH and a host pop.
- While the serialiser is busy (from `MOV ser` until the frame ends) the TX FIFO is the serialiser's: a program PULL
  finds it empty (a blocking PULL stalls, a non-blocking one loads X), whatever the level. The serialiser's own pull and
  a host push in the same clock both happen.

### Engine 0's TX FIFO (64 words)

A one-port memory (64 x 16, reads on the clock: `src/fifo_mem.v`, flip-flops, or IHP's `RM_IHPSG13_1P_64x16_c2` with
`+define+USE_SRAM`) behind a **head register**, which holds the oldest word. PULL and the serialiser take the head only.
Each clock, decided from the state at the start of the clock:
- An accepted host push writes the memory. The memory does one access per clock; a write has priority over a read.
- If there is no accepted host push, the head is empty or is taken this clock, and the memory holds a word not yet in
  the head, that word is read into the head. It is the head from the next clock.
- So a word pushed in clock k into an empty FIFO is ready from clock k + 2 when clock k + 1 has no host push (one clock
  later than on engines 1 and 2); each further clock with a host push delays it one clock more. After the head is taken
  in a clock with a host push, the next word is ready one clock later than after one taken in a clock without.
- While the head is empty, PULL and the serialiser see the FIFO as empty, whatever the level: a blocking PULL stalls,
  a non-blocking one loads `x`; the serialiser waits in FILL and underruns in DATA (see Serialiser).
- The level (STATUS and SERSTAT, `MOV status` `[3:0]`, the full check on host pushes) counts every word in the FIFO,
  the head included.
- The host port completes at most one word per 16 SPI clocks, so it never pushes in two consecutive clocks: on the chip
  a read waits at most one clock behind a push.

## Reserved encodings (defined, so random programs are a fair test)

`OUT` destinations 3 and 7 discard the data (the OSR still shifts).
`MOV` destination 4 does nothing; `MOV` op 3 is a plain copy. `SET` destinations 3, 5, 6, 7 do nothing.
`TIME` actions 6 and 7 do nothing. In `PUSH/PULL`, bits 4:0 are ignored. In `IN/OUT`, bit 4 of the count is ignored
(only bits 3:0 count; 0 means 16). `WAIT` indices 16-23 read the pins of those numbers (reserved for later use).
v0.3 took three former reserved encodings: `IN` source 7 (the CRC), `MOV` destination 3 (`ser`) and `TIME` action 5
(CRC reset); `WAIT` index 24 reads the serialiser instead of pin 24 on engine 0.

## The eight instructions

**0 JMP** `[7:5] cond, [4:0] addr`.
Conditions: 0 always; 1 `!x` (x == 0); 2 `x--` (x != 0, then x -= 1 either way); 3 `!y`;
4 `y--`; 5 `x!=y`; 6 `pin` (`jmp_pin` high); 7 `!osre` (OSR not empty).

**1 WAIT** `[7] level, [6] timeout, [5] rel, [4:0] index`.
Stall until the pin is at `level`. Pin = `index` if `rel = 0`, else `in_base + index`.
On engine 0, pin number 24 (whether from `index` or `in_base + index`, modulo 32) is the serialiser's busy flag
instead of a pin: `wait 0, ser` stalls until the frame has gone out. On engines 1 and 2 number 24 is a pin as before
(it reads 0 on the chip), so `wait 0, ser` passes at once there and `wait 1, ser` never does. The timeout works as
for a pin. Likewise on engine 0 number 25 is the receiver's frame-ready flag (v0.4): `wait 1, 25` stalls until a
received frame is in the buffer.
If `timeout = 1`: on each tick spent waiting, if `y == 0` jump to `fault_addr` (the WAIT is abandoned,
treated as a completed jump, so its delay applies); otherwise `y -= 1`. Load Y with the timeout in ticks beforehand.

**2 IN** `[7:5] src, [4:0] n` (n = 0 means 16).
Sources: 0 pins (from `in_base`); 1 x; 2 y; 3 zeros; 4 isr; 5 osr; 6 stopwatch; 7 the CRC register's low 16 bits.
Takes the low `n` bits of the source. Shift right: `isr = (isr >> n) | (data << (16 - n))`.
Shift left: `isr = (isr << n) | data`. Then `isr_count = min(16, isr_count + n)`.
Every IN, whatever its source, also offers one bit to the CRC unit: the first bit it shifted in, which is `data` bit 0
with `in_right` and `data` bit `n - 1` without (section "CRC unit"). `in crc, 16` therefore steps the register once
more, with its own bit 0, after the value has been taken.

**3 OUT** `[7:5] dst, [4:0] n` (n = 0 means 16).
Shift right: `data = osr & mask(n)`, `osr >>= n`. Shift left: `data = osr >> (16 - n)`, `osr <<= n`.
Then `osr_count = min(16, osr_count + n)`.
Destinations: 0 pins (`n` pins from `out_base`); 1 x; 2 y; 3 nothing; 4 pin directions; 5 pc (a jump);
6 isr (also `isr_count = n`).

**4 PUSH / PULL** `[7] 1 = pull, [6] if-full / if-empty, [5] block`.
PUSH: if `[6]` and `isr_count < 16`, do nothing. Else RX FIFO full: stall if block, else do nothing.
Otherwise push `isr`, then `isr = 0`, `isr_count = 0`.
PULL: if `[6]` and `osr_count < 16`, do nothing. Else TX FIFO empty (engine 0: no head word ready, see "Host and FIFO
timing") **or the serialiser busy**: stall if block, else `osr = x`. Otherwise `osr` = popped word, `osr_count = 0`.

**5 MOV** `[7:5] dst, [4:3] op, [2:0] src`.
Destinations: 0 pins (from `out_base`); 1 x; 2 y; 3 ser (the serialiser: start a frame of that many words, 0 stops
it; engines 1 and 2, and engine 0 with SERCFG enable 0, do nothing); 5 pc; 6 isr (`isr_count = 0`); 7 osr (`osr_count = 0`).
Ops: 0 copy; 1 invert (bitwise NOT); 2 bit-reverse (16 bits).
Sources: 0 pins (16 from `in_base`); 1 x; 2 y; 3 zero; 4 stopwatch; 5 status; 6 isr; 7 osr.
`status` = `[3:0]` TX FIFO level, saturating at 15; `[7:4]` RX FIFO level; `[8]` serialiser busy; `[9]` serialiser
underrun; other bits 0. Bits 8 and 9 are 0 on engines 1 and 2.

**6 SET** `[7:5] dst, [4:0] value`.
Destinations: 0 pins (`set_count` from `set_base`); 1 x; 2 y; 4 pin directions (same pins).
X and Y get the value zero-extended.

**7 TIME** `[7:5] action`.
0 start (`sw = 0`, run); 1 stop; 2 capture into x; 3 capture into y; 4 capture into isr (`isr_count = 16`, ready to push);
5 reset the CRC register to `crcinit` (`time crc reset`).
Capture does not stop the stopwatch. The count is in ticks, and saturates at 65535.
On every tick, a running stopwatch adds 1 **before** the instruction executes, so a capture
gives exactly the number of ticks from the `time start` to the capture.

## CRC unit (v0.3; every engine)

**Built only where the build asks for it (`CRC = 1`).** The ASIC build has no CRC unit (7 Nov 2026): `crc` reads 0,
CRCPOLY, CRCINIT and CRC read 0, `IN` source 7 shifts in zeros and `TIME 5` does nothing. SERCFG `[4]` (CRC append)
then appends 32 zeros (ones if `[5]`), so an Ethernet frame is sent with the FCS computed by the host as the last two
FIFO words and `[4]` off. The encodings are unchanged.

A 32-bit register `crc`, right-shifting (reflected) form. One step with bit `b`:
`crc = (crc >> 1) ^ (crcpoly if (crc & 1) ^ b else 0)`. A polynomial and start value with zero upper halves stay a
16-bit CRC in the low half (Modbus RTU: `crcpoly = 0xA001`, `crcinit = 0xFFFF`; Ethernet: `0xEDB88320`, `0xFFFFFFFF`,
complemented on append). Reset: `crc = crcinit` when the engine starts, on `TIME 5`, and when the serialiser starts
a frame. A reset and a step in the same clock: the reset wins and the bit is lost.

Which bits it takes is SERCFG bit 6 (fixed at 0 on engines 1 and 2):
- **0, IN mode**: one step per executed IN instruction, with the first bit that IN shifted in (`data` bit 0 with
  `in_right`, bit `n - 1` without). A receiver that wants every bit through the CRC shifts one bit per IN.
- **1, SER mode**: one step per data bit the serialiser sends, in the clock that bit's first half starts, except the bits
  of the first SERCFG `[12:10]` words of each frame (the Ethernet preamble and SFD). The appended CRC bits and the end
  marker are not fed back.

Read by the program as `IN` source 7 (low 16 bits; this IN steps the register once more in IN mode) and by the host as
registers 0x31 (low) and 0x32 (high); the host reads the running value, never complemented.

## Serialiser (v0.3; engine 0 only)

Runs on the system clock, not the engine tick. A **half-bit** is `serdiv + 1` clocks; a bit is two half-bits.
Phases: FILL, DATA, CRC, END. State visible to programs: `ser_busy` (`WAIT` 24, `status` bit 8) and `ser_under`
(`status` bit 9); to the host: STATUS bits 14 and 15 (docs/host_port.md).

- **Start.** `MOV ser, src` with SERCFG enable 1 and `src != 0` (the value after the MOV op): `ser_busy = 1`,
  `ser_under = 0`, word count = `src`, skip count = SERCFG `[12:10]`, `crc = crcinit`, phase FILL. It restarts a frame
  already in progress. `src = 0`: `ser_busy = 0` (abort: the pins are released at once, words left in the FIFO stay).
  With enable 0, or on engines 1 and 2, `MOV ser` does nothing.
- **FILL.** The serialiser waits, busy but not driving the pins, until the TX FIFO holds at least the word count or is
  full (64), and its head word is ready (see "Engine 0's TX FIFO"). Then, in that clock, it pulls the first word and starts its first bit. So the host may push the count and
  the words in one burst at any speed: nothing goes out until the whole frame is in. Underrun cannot happen in FILL.
- **DATA.** Bits go out from the shift register, bit 0 first with `out_right`, bit 15 first without; a new bit every
  two half-bits. When the last bit of a word has had its two half-bits: if words remain and the FIFO's head word is ready, the
  next word is pulled in that clock (no gap on the line); if words remain and no head word is ready (the FIFO is empty,
  or its next word was pushed into an empty FIFO in the clock before), **underrun**: `ser_busy =
  0`, `ser_under = 1`, pins released, the count abandoned; if none remain, on to CRC (SERCFG `[4]`), else END (`[3]`),
  else idle (`ser_busy = 0`).
- **CRC.** 32 bits of the CRC register, read live as each is sent: bit 0 first with `out_right`, bit 31 first without,
  each inverted if SERCFG `[5]`. Then END if `[3]`, else idle.
- **END.** The line held high for 6 half-bits (Ethernet's TP_IDL), then idle.
- **Line coding.** NRZ: both half-bits carry the bit. Manchester (SERCFG `[1]`): the first half-bit carries the inverse
  of the bit, the second the bit (a 1 is a rising edge mid-bit: IEEE 802.3, DALI). END is high in either.
- **Pins.** While shifting (DATA, CRC, END; not FILL) the serialiser's level replaces the program's on `out_base`, and
  its inverse replaces the program's on `out_base + 1` (modulo 32) if SERCFG `[2]`. `out_val` itself is untouched, so
  the program's levels return when the serialiser lets go. Directions are the program's business (`set pindirs`).
- **Timing.** Each half-bit is exactly `serdiv + 1` clocks; the first bit's first half is on the pin at the end of the
  clock that pulls the word. A frame of W words with CRC and end marker drives the pins for
  `(32 W + 64 + 6) x (serdiv + 1)` clocks. `ser_busy` becomes 1 at the end of the clock in which `MOV ser` executes and
  0 at the end of the clock in which the last half-bit ends. `WAIT` 24, `MOV status` and PULL see `ser_busy` as it was
  at the start of the clock, like the FIFO levels.
- **Flags.** `ser_under` stays set until the next `MOV ser` with a non-zero count.

## Receiver (v0.4; engine 0 only)

Engine 0 sends or receives, one at a time (half duplex). The receiver decodes Manchester from one input pin into the same
64-word buffer the serialiser sends from. Checked against the model (`model/engine.py`, `model/test_receive.py`) every
clock by `model/cosim.py`.

- **Direction.** Engine state, transmit after reset (and whenever the engine is stopped, since a stopped engine is held
  in reset). A SERCFG write changes it only if bits `[15:13]` are `101` (the key); bit 7 is then the direction (1 receive,
  0 transmit). The change is taken only when idle: the serialiser not busy and no frame coming in. Otherwise it is
  refused, nothing changes, and RXSTAT's refused flag is set. A change that is taken empties the buffer, resets the
  receiver and stops the serialiser, even if `MOV ser` executes in the same clock. SERCFG bit 7 reads back the direction
  in force.
- **Interlocks in receive mode.** `MOV ser` does nothing and sets the refused flag; host writes to the buffer (0x26) are
  dropped; `PULL` finds the buffer empty (the received words are the host's).
- **Arm.** An RXCFG write with bit 7 set empties the buffer, clears the status and listens for one frame.
- **Sampling.** Two samples of the receive pin per clock: the level at the falling edge of the clock (a latch outside the
  engine), then the level at the rising edge, in that order, both through flip-flops matched so they stay in time
  order. Both bypass the chip's glitch filter: receive does not depend on FILTER, which stays as set for the other pins.
  With RXCFG `[6]` clear only the rising-edge sample is used. Time is counted in half-clocks.
- **Decoding.** An edge at least RXGAP half-clocks after the last taken edge is taken as a mid-bit edge: rising = 1,
  falling = 0. Edges sooner than that are bit boundaries and are ignored. No taken edge for 2 x RXGAP half-clocks ends the
  frame. The first edge after idle is taken. RXGAP is 3/4 of a bit: 6 for 10 Mbit/s at 40 MHz, 3 x (SERDIV + 1) for the
  serialiser's own rate.
- **Framing.** Hunting: 16 or more alternating bits ended by two 1s (the Ethernet preamble and SFD) lock; the next bit is
  the first of the frame. A lone pulse, or a run that stops, returns to idle. Raw mode (RXCFG `[5]`): no hunt, bits are
  kept from the first taken edge.
- **Words.** Bits shift into a 16-bit register, bit 0 first with `in_right`, bit 15 first without; every 16 bits the word
  is written to the buffer. At the end of the frame a partial word is written with its bits brought down to bit 0, and
  their number is kept in RXSTAT. A word that finds the buffer full is dropped and sets overrun. The frame is then
  ready (`WAIT` 25, RXSTAT bit 0, the chip's IRQ) until the next arm or direction change.
- **Measured on the model** (10 Mbit/s, 40 MHz, random clock phase): with both clock edges every frame is right with each
  edge moved by up to +-7 ns; with the rising edge only, any jitter fails.

## Assembly language

```
label:
    opname args        [side N] [D]     ; comment
.side_set N [opt] [pindirs]             ; side-set width, optional enable, writes directions (side_dir)
.wrap_target / .wrap                    ; mark wrap_bottom / wrap_top
```

Examples: `jmp x--, loop` / `wait 1, pin 3` / `wait 0, rel 0, timeout` / `wait 0, ser` / `in pins, 1` / `in crc, 16` /
`out pins, 1` / `pull block` / `push noblock` / `mov isr, ~x` / `mov x, ::osr` (bit-reverse) / `mov ser, osr` /
`set pins, 1` / `time start` / `time capture x` / `time crc reset`.
