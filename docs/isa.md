# Engine instruction set, v0.1 (2 Nov 2026)

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
| TX FIFO, RX FIFO | 4 x 16 each | to and from the host |

Reset: everything 0, except `osr_count = 16` (empty) and `pc = start`.

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
| `in_base` | 5 | `IN pins` reads from here upwards; `WAIT` relative pins count from here |
| `jmp_pin` | 5 | pin tested by `JMP PIN` |
| `out_right`, `in_right` | 1, 1 | shift direction: 1 = right (LSB first, UART), 0 = left (MSB first, SPI/I2C) |
| `fault_addr` | 5 | where a timed-out `WAIT` jumps to |

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
  If the instruction and the side-set write the same pin, the side-set wins.
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
  The word becomes visible to the engine from the next clock.
- The host's pop from the RX FIFO is accepted only if it was not empty at the start of the clock;
  the host gets the word that was at the head.
- The engine's PULL / PUSH and `MOV status` see the FIFO levels at the start of the clock.
- So an engine PULL and a host push in the same clock both happen (count -1 +1), and so do an engine PUSH and a host pop.

## Reserved encodings (defined, so random programs are a fair test)

`IN` source 7 reads zeros. `OUT` destinations 3 and 7 discard the data (the OSR still shifts).
`MOV` destinations 3 and 4 do nothing; `MOV` op 3 is a plain copy. `SET` destinations 3, 5, 6, 7 do nothing.
`TIME` actions 5-7 do nothing. In `PUSH/PULL`, bits 4:0 are ignored. In `IN/OUT`, bit 4 of the count is ignored
(only bits 3:0 count; 0 means 16).

## The eight instructions

**0 JMP** `[7:5] cond, [4:0] addr`.
Conditions: 0 always; 1 `!x` (x == 0); 2 `x--` (x != 0, then x -= 1 either way); 3 `!y`;
4 `y--`; 5 `x!=y`; 6 `pin` (`jmp_pin` high); 7 `!osre` (OSR not empty).

**1 WAIT** `[7] level, [6] timeout, [5] rel, [4:0] index`.
Stall until the pin is at `level`. Pin = `index` if `rel = 0`, else `in_base + index`.
If `timeout = 1`: on each tick spent waiting, if `y == 0` jump to `fault_addr` (the WAIT is abandoned,
treated as a completed jump, so its delay applies); otherwise `y -= 1`. Load Y with the timeout in ticks beforehand.

**2 IN** `[7:5] src, [4:0] n` (n = 0 means 16).
Sources: 0 pins (from `in_base`); 1 x; 2 y; 3 zeros; 4 isr; 5 osr; 6 stopwatch.
Takes the low `n` bits of the source. Shift right: `isr = (isr >> n) | (data << (16 - n))`.
Shift left: `isr = (isr << n) | data`. Then `isr_count = min(16, isr_count + n)`.

**3 OUT** `[7:5] dst, [4:0] n` (n = 0 means 16).
Shift right: `data = osr & mask(n)`, `osr >>= n`. Shift left: `data = osr >> (16 - n)`, `osr <<= n`.
Then `osr_count = min(16, osr_count + n)`.
Destinations: 0 pins (`n` pins from `out_base`); 1 x; 2 y; 3 nothing; 4 pin directions; 5 pc (a jump);
6 isr (also `isr_count = n`).

**4 PUSH / PULL** `[7] 1 = pull, [6] if-full / if-empty, [5] block`.
PUSH: if `[6]` and `isr_count < 16`, do nothing. Else RX FIFO full: stall if block, else do nothing.
Otherwise push `isr`, then `isr = 0`, `isr_count = 0`.
PULL: if `[6]` and `osr_count < 16`, do nothing. Else TX FIFO empty: stall if block, else `osr = x`.
Otherwise `osr` = popped word, `osr_count = 0`.

**5 MOV** `[7:5] dst, [4:3] op, [2:0] src`.
Destinations: 0 pins (from `out_base`); 1 x; 2 y; 5 pc; 6 isr (`isr_count = 0`); 7 osr (`osr_count = 0`).
Ops: 0 copy; 1 invert (bitwise NOT); 2 bit-reverse (16 bits).
Sources: 0 pins (16 from `in_base`); 1 x; 2 y; 3 zero; 4 stopwatch; 5 status (TX FIFO level in bits 3:0, RX in 7:4); 6 isr; 7 osr.

**6 SET** `[7:5] dst, [4:0] value`.
Destinations: 0 pins (`set_count` from `set_base`); 1 x; 2 y; 4 pin directions (same pins).
X and Y get the value zero-extended.

**7 TIME** `[7:5] action`.
0 start (`sw = 0`, run); 1 stop; 2 capture into x; 3 capture into y; 4 capture into isr (`isr_count = 16`, ready to push).
Capture does not stop the stopwatch. The count is in ticks, and saturates at 65535.
On every tick, a running stopwatch adds 1 **before** the instruction executes, so a capture
gives exactly the number of ticks from the `time start` to the capture.

## Assembly language

```
label:
    opname args        [side N] [D]     ; comment
.side_set N [opt]                       ; side-set width, optional
.wrap_target / .wrap                    ; mark wrap_bottom / wrap_top
```

Examples: `jmp x--, loop` / `wait 1, pin 3` / `wait 0, rel 0, timeout` / `in pins, 1` /
`out pins, 1` / `pull block` / `push noblock` / `mov isr, ~x` / `mov x, ::osr` (bit-reverse) /
`set pins, 1` / `time start` / `time capture x`.
