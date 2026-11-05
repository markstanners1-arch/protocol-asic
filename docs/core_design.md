# Core design, first draft (2 Nov 2026)

The paper stage: what goes in, what comes out, and the blocks in between.
Nothing here is built yet. The **open questions** at the bottom need Mark's call.

## The pins we get (Tiny Tapeout)

- `ui_in[7:0]`: 8 inputs only
- `uo_out[7:0]`: 8 outputs only
- `uio[7:0]`: 8 two-way pins, each with its own output enable (`uio_oe`)
- `clk`, `rst_n`

The two-way pins are what make I2C possible. Open-drain = "drive low" or "let go"
(output enable off, the pull-up takes the line high). So I2C and anything else
that shares a wire lives on `uio`.

Proposed split:

| Pins | Use |
|---|---|
| `ui_in[3:0]` | **host port**: a little SPI slave (CS, SCK, MOSI) through which the host loads programs, sends and receives data, reads status |
| `uo_out[0]` | host port MISO |
| `uo_out[1]` | host interrupt ("data waiting") |
| `ui_in[7:4]` | 4 protocol inputs |
| `uo_out[7:2]` | 6 protocol outputs |
| `uio[7:0]` | 8 two-way protocol pins |

On the Tiny Tapeout dev board the host is the RP2040 on the carrier. On the bench it could be an ESP32.

## Block diagram

```
                 host SPI (4 pins)
                        |
              +---------v----------+
              |  host port          |  writes program memory and config,
              |  (SPI slave + regs) |  feeds / empties the FIFOs, reads status
              +--+-------------+---+
                 |             |
        +--------v---+   +-----v------+        program memory
        | ENGINE A    |   | ENGINE B   | <----  64 x 16-bit words, shared,
        |             |   |            |        each engine runs its own slice
        +--+-------+--+   +--+-------+-+
           |       |         |       |
        TX FIFO  RX FIFO   TX FIFO  RX FIFO     4 words deep each, to/from host
                 \             /
              +---v-----------v---+
              |  pin crossbar      |  any engine can own any pin
              +---------+---------+
                        |
              +---------v---------+
              |  input conditioning|  per input: 2 flip-flop synchroniser,
              |  (every input pin) |  then a glitch filter of 0-15 clocks
              +---------+---------+
                        |
                   the 20 protocol pins
```

## One engine, in 74-series terms

Each engine is a tiny CPU that runs **one instruction per tick** of its own clock,
so every instruction has an exact, known time. That's what makes protocols in firmware
possible: the timing is counted, not hoped for.

| Block | What it is | Size |
|---|---|---|
| Clock divider | 16-bit down-counter; the engine ticks when it hits zero | 16 FF |
| Program counter | 6-bit counter with load (for jumps) and wrap limits | 6 FF |
| X, Y | two 16-bit scratch registers that can count down (loop counters, timeouts) | 32 FF |
| OSR (output shift register) | 16 bits; the host's data goes in, bits shift out to pins | 16 FF + count |
| ISR (input shift register) | 16 bits; bits shift in from pins, the full word goes to the host | 16 FF + count |
| Delay counter | 5 bits: stretches any instruction by up to 31 extra ticks | 5 FF |
| **Stopwatch** (new) | 16-bit up-counter, started and stopped by instructions | 16 FF |
| Instruction decoder | gates and muxes | |

Rough total: about 150 flip-flops per engine plus logic. Program memory (64 x 16 = 1024 bits)
is the biggest item. Flip-flops first; IHP's SRAM later if area gets tight.
We're well inside the 24,000-cell budget either way. We have room for more engines if we want them.

## Instruction set

Every instruction is 16 bits: `[15:13]` opcode, `[12:8]` delay / side-set, `[7:0]` arguments.
**Side-set** = also set one or two pins on the same tick, for free. That's how a clock line and a data line move together.

| Op | Instruction | Does |
|---|---|---|
| 0 | `JMP cond, addr` | jump if: always, X zero, X-- not zero, Y zero, Y-- not zero, X != Y, pin high, OSR empty |
| 1 | `WAIT level, pin [, timeout]` | stall until a pin reaches a level. **New:** an optional timeout using Y, which jumps to a fault address instead of hanging forever (a stuck I2C bus) |
| 2 | `IN src, n` | shift n bits into the ISR from pins / X / Y |
| 3 | `OUT dst, n` | shift n bits out of the OSR to pins / X / Y / pin directions / PC |
| 4 | `PUSH` / `PULL` | ISR to the RX FIFO / TX FIFO to the OSR (wait or don't) |
| 5 | `MOV dst, src` | copy between X, Y, ISR, OSR, pins, stopwatch (optionally inverted or bit-reversed) |
| 6 | `SET dst, value` | put a 5-bit number into pins / pin directions / X / Y |
| 7 | **`TIME`** (new) | stopwatch control: start, or capture the elapsed ticks into X or the ISR. Combined with `WAIT`, it measures how long a pin took to change |

Ops 0-6 follow the RP2040 PIO closely, on purpose. It's a proven design.
What's ours is op 7, the WAIT timeout, input conditioning on every pin, and the way we verify it.

## Two programs on paper

**UART transmit** (engine clock = 8 x baud, so one bit = 8 ticks):

```
.wrap_target
    pull   block        side 1 [7]  ; wait for a byte; line idles high; also the stop bit
    set    x, 7         side 0 [7]  ; start bit: low for 8 ticks; 8 bits to go
bitloop:
    out    pins, 1                  ; next data bit, LSB first   (1 tick)
    jmp    x--, bitloop        [6]  ; loop                       (7 ticks) -> 8 per bit
.wrap
```

**Measure the other end's baud rate** (the "measure before it talks" idea).
The other device sends 'U' (0x55: alternating bits, so every bit gives an edge):

```
    wait   0, pin 0          ; falling edge: start bit begins
    time   start
    wait   1, pin 0          ; first rising edge: start bit ends
    time   capture x         ; X = one bit time, in ticks
    mov    isr, x
    push                     ; tell the host: "the other end runs at this speed"
```

The same pattern measures an I2C bus's edge speed. Let go of the line, `time start`,
`wait 1`, `time capture`. The count is the RC time of the pull-up against the bus capacitance.

## How we'll know it works

1. A **Python model** of the engine, written from this document, not from the Verilog.
2. The Verilog engine and the Python model run the same program and are compared **every tick**.
   Any difference is a bug in one or the other. Then thousands of random programs, not just the ones we wrote.
3. Model "other ends" (a UART receiver, an I2C slave that stretches its clock, a sloppy UART running 3% fast,
   a noisy line) to test against.
4. Then the FPGA, against real boards.

## Decisions (2 Nov 2026, Mark: go with the leanings)

1. **Two engines.**
2. **16-bit registers.**
3. **The measuring side is the headline** (stopwatch, WAIT timeout, input conditioning).
4. **Host port is an SPI slave.**
5. Bench gripes: none yet; keep asking as we go.

One change while writing the exact encoding: each engine gets **its own 32-word program memory**
(64 words in all, as planned) instead of one shared 64-word memory. A jump then needs only a 5-bit address,
which fits the 16-bit instruction. The exact encoding is in `docs/isa.md`.

**3 Nov 2026: three engines.** The first layout used a third of the 6x4 tile, so the chip grew: four engines (61 % of
the core) failed detailed placement twice, three (49.5 %) laid out cleanly with timing met, so the chip has three
(A-C), each with its own 32-word program memory. The MachXO3L kit builds two, the Cyclone IV board three. The host command grew to 16 bits to carry a 3-bit engine number, and register 0x2A tells the
host how many engines there are (`docs/host_port.md` v0.2). The lowest-numbered engine driving a pin wins.
The 20 protocol pins are shared: a UART, an I2C and an SPI at once, with pins to spare.

## Hierarchy (5 Nov 2026): engine, cluster, chip

The Verilog is three levels, each a module with its own parameters. Behaviour is that of the 3 Nov chip; only the
module boundaries are new.

```
protocol_chip  (src/chip.v)        NENG = 3 (engines per cluster, 1-4), NCLUSTER = 1 (clusters, 1-64)
  host_spi                         SPI slave; command = [15] read, [14:12] engine, [11:6] cluster, [5:0] register
  synchronisers + glitch_filter    the 13 real inputs, one chip-wide FILTER setting (register 0x29)
  ID register (0x2A)               chip-wide, unchanged: [7:4] spec version 2, [3:0] engines
  cluster[0..NCLUSTER-1]  (src/cluster.v)    NENG, NSLOT = 4, NPIN = 32
    setting registers              one set per populated engine (0x20-0x25, 0x27, 0x28); a slot past NENG-1 is absent
    engine[0..NENG-1]  (src/engine.v)        the cell: program store, x/y, ISR/OSR, FIFOs, stopwatch, WAIT, side-set
    pin bank                       NPIN pin numbers seen by every engine; mux and "lowest engine wins" arbitration
    irq                            OR of the engines' RX-FIFO-not-empty
  pins                             cluster 0's bank to the package: 0-7 uio, 8-13 uo_out[7:2], 15-19 ui_in[7:3]
```

- `NSLOT` is the number of engine slots the cluster's decode and arbitration are laid out for; `NENG` is how many are
  populated. The host's 3-bit engine field addresses slots; a slot from `NENG` to 7 ignores writes and reads 0 (as an
  engine number past the last did before).
- The cluster number is the command's bits `[11:6]`, which every host program so far sends as 0. Cluster 0 is the
  chip; a number from `NCLUSTER` to 63 reads 0 for every register, chip-wide ones included, and its writes are
  ignored. Reads decode the number directly; writes and FIFO pops use a copy registered one clock later, which is
  settled long before any strobe (a strobe follows the command word by at least 16 SCK edges).
- The package has one pin bank, so with `NCLUSTER` above 1 only cluster 0 reaches the pins; the others are reachable
  through the host port only.
- Proof of no behaviour change (branch `cluster`, 5 Nov 2026): cosim 400,000 clocks for three seeds and once with the
  IHP SRAM store, every clock identical; whole-chip test PASS at `NENG=3`, `NENG=2` and `LATE=1`, plus five new checks
  on cluster numbers 1, 2 and 63; two planted bugs in `cluster.v` (engine 1's pin bank rotated by 8; CLKDIV taken from
  the mirrored slot) each failed the whole-chip test at its first measurement.

## Serialiser and CRC unit (5 Nov 2026, ISA v0.3)

Engine 0 has a **bit-cell serialiser** (`src/serialiser.v`) and a 64-word TX FIFO; every engine has a **CRC unit**
(`src/crc32.v`). Exact rules: `docs/isa.md`, sections "Serialiser" and "CRC unit"; registers: `docs/host_port.md`.

| Block | What it is | Flip-flops |
|---|---|---|
| Shift register | 16 bits, loaded from the TX FIFO head, shifts right (LSB first) or left (MSB first) by `out_right` | 16 |
| Half-bit divider | 16-bit down-counter, reloads from SERDIV: a half-bit is SERDIV + 1 clocks of the chip clock, not the engine tick | 16 |
| Half-bit flip-flop, bit counter | 1 + 5 bits: which half of which bit (0-15 data, 0-31 CRC, 0-5 end marker) | 6 |
| Word counter | 16-bit down-counter loaded by `MOV ser`: words still to pull | 16 |
| Phase | 2 bits: FILL (wait until the whole frame is in the FIFO), DATA, CRC, END | 2 |
| Skip counter | 3 bits: the first N words of a frame bypass the CRC (Ethernet's preamble) | 3 + 1 |
| Busy, underrun flip-flops | `WAIT` 24, `MOV status` bits 8-9, STATUS bits 14-15 | 2 |
| Encoder mux | NRZ: the bit; Manchester: the inverse in the first half, the bit in the second; END: 1 | |
| Pin mux | while sending, the line replaces the program's level on `out_base`, its inverse on `out_base + 1` (differential) | |
| CRC unit, per engine | 32-bit shift register with an XOR per bit under a gated polynomial (the reflected form), fed by IN or by the serialiser | 32 |
| CRC settings, per engine | CRCPOLY and CRCINIT, 32 bits each | 64 |

Engine 0's TX FIFO is 64 x 16 (engines 1 and 2 keep 4 words of flip-flops), so a minimum Ethernet frame (34 words with
the preamble; the FCS comes from the CRC unit) is in the chip before its first bit goes out.

Engine 0's TX FIFO is a one-port memory (`src/fifo_mem.v`: 64 x 16 flip-flops by default, IHP's
`RM_IHPSG13_1P_64x16_c2` with `+define+USE_SRAM`, both reading on the clock) behind an arbiter and a head register: a
6-bit write pointer, a 6-bit read pointer, a 7-bit count and a head-valid flip-flop. A host push writes the memory and
has the port; on a clock without a push, an empty or departing head is refilled from the memory. PULL and the
serialiser take the head. The head word is captured into a 16-bit register on the clock after each read, so it does
not depend on the memory output holding between reads. Exact timing: `docs/isa.md`, "Engine 0's TX FIFO". The FPGA
builds use the flip-flop memory.

The FPGA wrappers take the parameters `SER0`, `CRC` and `TXDEPTH0` (`src/chip.v`). The MachXO3L kit and the Cyclone IV
board build with `SER0 = 0, CRC = 0, TXDEPTH0 = 4`: the v0.2 engines (MOV ser and TIME 5 do nothing, IN source 7 and
the new registers read 0). `bash fpga/machxo3/build.sh ser` builds the kit with one engine carrying the serialiser, the
CRC unit and the 64-word TX FIFO.

1. **Two engines or one?** Two lets, say, an SPI master and a UART run at once, or TX and RX separately. *Lean: two.*
2. **16-bit registers or 32?** 16 is enough for UART/SPI/I2C and saves area; Ethernet would want 32. *Lean: 16.*
3. **Is the measuring side (stopwatch, WAIT timeout, glitch filters) our headline?** *Lean: yes.*
4. **Host port as an SPI slave?** Simple, and the RP2040 or an ESP32 can drive it. *Lean: yes.*
5. Anything from the bench years that always annoyed you about these buses? That's where better ideas come from.

## Still to check

- What clock speed IHP 130 nm can manage for this (aim 50 MHz; layout will tell us).
- Whether IHP SRAM blocks are available inside a Tiny Tapeout tile.
- The Tiny Tapeout carrier board's clock and pin arrangements for the host port.
