# Core design

What goes in, what comes out, and the blocks in between. The exact engine rules are in `docs/isa.md`, the host's
registers in `docs/host_port.md`, the input filter in `docs/input_filter.md`.

## Pins (Tiny Tapeout)

| Pins | Use |
|---|---|
| `ui_in[0]`, `ui_in[1]`, `ui_in[2]` | **host port**, an SPI slave: CS (active low), SCK, MOSI. The host loads programs, sends and receives data and reads status through it |
| `uo_out[0]` | host port MISO |
| `uo_out[1]` | IRQ: high while any engine's RX FIFO holds data, or engine 0 has a received frame ready |
| `ui_in[7:3]` | engine pins 15-19, input only |
| `uo_out[7:2]` | engine pins 8-13, output only |
| `uio[7:0]` | engine pins 0-7, two-way, each with its own output enable (`uio_oe`) |
| `clk`, `rst_n` | chip clock (40 MHz on Tiny Tapeout), reset |

The two-way pins are what make I2C possible. Open drain is "drive low" or "let go" (output enable off, the pull-up takes
the line high), so I2C and anything else that shares a wire lives on `uio`. Engine pin 14 is not connected.

Engine 0's receive pin is any input pin, chosen by RXCFG `[4:0]`. The Tiny Tapeout wrapper holds that pin at the falling
edge of the clock in a latch (`sg13cmos5l_dlhq_1`, open while the clock is high), so the receiver gets two samples per
clock (`docs/isa.md`, "Receiver and full duplex"). The FPGA wrappers use a falling-edge flip-flop instead.

On the Tiny Tapeout demo board the host is the board's RP2040. On the bench it is an ESP32 or a Raspberry Pi Pico 2
(`docs/bench_wiring.md`).

## Builds

The same `src/` builds every version; the wrappers set the parameters of `protocol_chip` (`src/chip.v`). Register 0x2A
(ID) reads `[7:4]` the spec version (2) and `[3:0]` the number of engines.

| Build | Engines | Engine 0 serialiser, receiver, buffer (1024 words in `src/`, 64 on the FPGAs) | CRC units | Memories | Clock | ID |
|---|---|---|---|---|---|---|
| Tiny Tapeout, IHP CMOS5L, 6x4 tiles (`tt_um_gosforth_protocol_emu`) | 4 (A-D) | serialiser, buffer and receiver | no | IHP SRAM macros | 40 MHz | 0x0024 |
| `src/chip.v` defaults (the whole-chip test's default) | 3 | yes | yes | flip-flops | | 0x0023 |
| MachXO3L Starter Kit, `fpga/machxo3/build.sh` | 2 | no (4-word TX FIFOs) | no | flip-flops | 12 MHz | 0x0022 |
| MachXO3L, `build.sh ser` | 1 | yes | yes | flip-flops | 12 MHz | 0x0021 |
| Cyclone IV EP4CE6, `fpga/cyclone4/build.sh` | 3 | no | no | flip-flops | 50 MHz | 0x0023 |
| Cyclone IV, `build.sh ser` | 2 | yes | no | flip-flops | 40 MHz (PLL) | 0x0022 |
| Mojo v3 (Spartan-6 LX9), `fpga/mojo/build.sh` | 3 | no | no | flip-flops | 50 MHz | 0x0023 |
| Mojo v3, `build.sh ser` (`clk40` for 40 MHz) | 2 | yes | yes | flip-flops | 50 or 40 MHz | 0x0022 |

A build without the serialiser has the v0.2 engines: `MOV ser` and `TIME 5` do nothing, `IN` source 7 and the
serialiser, CRC and receive registers read 0. A build without CRC units is described in `docs/isa.md`, "CRC unit".

## Block diagram

```
                 host SPI: CS, SCK, MOSI in; MISO, IRQ out
                        |
              +---------v-----------+
              |  host port           |  16-bit commands: program words, settings, FIFO words,
              |  (SPI slave)         |  status; chip-wide FILTER (0x29) and ID (0x2A) registers
              +---------+-----------+
                        |
     +------------------v-------------------------------------------+
     |  cluster: engine slots 0-3 (A-D), NENG of them populated       |
     |                                                                |
     |  +-----------+  +-----------+  +-----------+  +-----------+    |
     |  | ENGINE A  |  | ENGINE B  |  | ENGINE C  |  | ENGINE D  |    |   each engine: its own 32-word
     |  | serialiser|  |           |  |           |  |           |    |   program memory, 4-word TX and
     |  | receiver  |  |           |  |           |  |           |    |   RX FIFOs; engine 0 (A): a
     |  +-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+    |   1024-word TX buffer
     |        +--------------+------+-------+--------------+          |
     |                      pin bank: 32 pin numbers,                 |
     |                      the lowest engine driving a pin wins      |
     +------------------+-------------------------------------------+
                        |
              +---------v-----------+
              |  input conditioning  |  per input: 2 flip-flop synchroniser, then a glitch
              |  (every input pin)   |  filter (one chip-wide setting)
              +---------+-----------+
                        |
            19 engine pins: 0-7 two-way, 8-13 out, 15-19 in
```

## One engine, in 74-series terms

Each engine is a small CPU that runs **one instruction per tick** of its own clock, so every instruction has an exact,
known time: protocol timing is counted, not hoped for.

| Block | What it is | Flip-flops |
|---|---|---|
| Clock divider | 16-bit down-counter; the engine ticks when it reaches zero (CLKDIV + 1 chip clocks a tick) | 16 |
| Program counter | 5-bit counter with load (for jumps) and wrap limits | 5 |
| X, Y | two 16-bit scratch registers that can count down (loop counters, timeouts) | 32 |
| OSR (output shift register) | 16 bits: the host's data goes in, bits shift out to pins | 16 + count |
| ISR (input shift register) | 16 bits: bits shift in from pins, the full word goes to the host | 16 + count |
| Delay counter | 5 bits: stretches any instruction by up to 31 extra ticks | 5 |
| Stopwatch | 16-bit up-counter, started, stopped and captured by instructions | 16 |
| Program memory | 32 x 16, one port, reads on the clock (section "Memory") | |
| TX and RX FIFOs | 4 x 16 each, to and from the host (engine 0's TX: 1024 x 16; 64 x 16 on the FPGA builds) | |
| Instruction decoder | gates and muxes | |

## Instruction set

Every instruction is 16 bits: `[15:13]` opcode, `[12:8]` delay / side-set, `[7:0]` arguments.
**Side-set** sets one or two pins on the same tick as the instruction: that is how a clock line and a data line move
together.

| Op | Instruction | Does |
|---|---|---|
| 0 | `JMP cond, addr` | jump if: always, X zero, X-- not zero, Y zero, Y-- not zero, X != Y, pin high, OSR not empty |
| 1 | `WAIT level, pin [, timeout]` | stall until a pin reaches a level; with the timeout, Y counts down each tick and at zero the WAIT jumps to a fault address instead of hanging (a stuck I2C bus) |
| 2 | `IN src, n` | shift n bits into the ISR from pins / X / Y / zeros / ISR / OSR / stopwatch / CRC |
| 3 | `OUT dst, n` | shift n bits out of the OSR to pins / X / Y / pin directions / PC / ISR |
| 4 | `PUSH` / `PULL` | ISR to the RX FIFO / TX FIFO to the OSR (wait or don't) |
| 5 | `MOV dst, src` | copy between X, Y, ISR, OSR, pins, stopwatch, status (optionally inverted or bit-reversed); `MOV ser` starts the serialiser |
| 6 | `SET dst, value` | put a 5-bit number into pins / pin directions / X / Y |
| 7 | `TIME` | stopwatch control: start, stop, capture the elapsed ticks into X, Y or the ISR; reset the CRC register. With `WAIT`, it measures how long a pin took to change |

Ops 0-6 follow the RP2040's PIO state machines closely. Op 7, the WAIT timeout, the input filter on every pin, the
serialiser, the receiver and the CRC unit are not part of PIO.

## Two example programs

**UART transmit** (`programs/uart_tx.asm`; one bit = 8 ticks, so baud = chip clock / (8 x (CLKDIV + 1))):

```
.side_set 1 opt
    set    pindirs, 1   side 1          ; drive the TX pin, idle high
.wrap_target
    pull   block        side 1 [7]      ; wait for a byte; line high; this is also the stop bit
    set    x, 7         side 0 [7]      ; start bit: low for 8 ticks; 8 data bits to go
bitloop:
    out    pins, 1                      ; next data bit                (1 tick)
    jmp    x--, bitloop        [6]      ; loop                         (7 ticks) -> 8 per bit
.wrap
```

**Measure the other end's bit time** (`programs/measure_baud.asm`). The other device sends 'U' (0x55), whose start bit
is the first low pulse:

```
    wait   1, pin 0          ; first see the line idle (high)
    wait   0, pin 0          ; falling edge: start bit begins
    time   start
    wait   1, pin 0          ; rising edge: start bit ends (0x55's bit 0 is a 1)
    time   capture isr       ; ISR = one bit time, in ticks
    push   block
done:
    jmp    done
```

## Hierarchy: engine, cluster, chip

The Verilog is three levels, each a module with its own parameters.

```
protocol_chip  (src/chip.v)        NENG (engines per cluster, 1-4; default 3, 4 on Tiny Tapeout), NCLUSTER = 1 (1-64)
  host_spi                         SPI slave; command = [15] read, [14:12] engine, [11:6] cluster, [5:0] register
  synchronisers + glitch_filter    the 13 real inputs, one chip-wide FILTER setting (register 0x29)
  ID register (0x2A)               chip-wide: [7:4] spec version 2, [3:0] engines
  cluster[0..NCLUSTER-1]  (src/cluster.v)    NENG, NSLOT = 4, NPIN = 32
    eng_slot[0..NENG-1]            one per populated engine; a slot past NENG-1 is absent
      setting registers + read mux the engine's own registers (0x20-0x25, 0x2B-0x37) and its read-back word
      engine  (src/engine.v)       the cell: program store, x/y, ISR/OSR, FIFOs, stopwatch, WAIT, side-set
    pin bank                       NPIN pin numbers seen by every engine; mux and "lowest engine wins" arbitration
    irq                            OR of the engines' RX-FIFO-not-empty (and engine 0's frame ready)
  pins                             cluster 0's bank to the package: 0-7 uio, 8-13 uo_out[7:2], 15-19 ui_in[7:3]
```

- `NSLOT` is the number of engine slots the cluster's decode and arbitration are laid out for; `NENG` is how many are
  populated. The host's 3-bit engine field addresses slots; a slot from `NENG` to 7 ignores writes and reads 0.
- Each `eng_slot` holds its engine's setting registers and picks its own read-back word by address; the cluster then
  picks one 16-bit word by engine number. Signals shared between slots: the write and pop strobes, engine number,
  address, write data, the pin bank, and per slot one read word and the RX-not-empty flag.
- The cluster number is the command's bits `[11:6]`. Cluster 0 is the chip; a number from `NCLUSTER` to 63 reads 0 for
  every register, chip-wide ones included, and its writes are ignored. Reads decode the number directly; writes and FIFO
  pops use a copy registered one clock later, which is settled long before any strobe (a strobe follows the command word
  by at least 16 SCK edges).
- The package has one pin bank, so with `NCLUSTER` above 1 only cluster 0 reaches the pins; the others are reachable
  through the host port only.

## Serialiser, receiver and CRC unit

Engine 0 has a **bit-cell serialiser** (`src/serialiser.v`), a **Manchester receiver** (`src/receiver.v`) and a 1024-word
buffer (64 on the FPGA builds); every engine in a build with `CRC = 1` has a **CRC unit** (`src/crc32.v`). Exact rules: `docs/isa.md`, sections
"Serialiser", "Receiver and full duplex" and "CRC unit"; registers: `docs/host_port.md`.

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

Engine 0's TX FIFO is 1024 x 16 (the other engines have 4 words of flip-flops), so a full-size Ethernet frame (1518
bytes, 759 words with the hardware preamble) is in the chip before its first bit goes out, and one arriving is held
whole. The 64-word FPGA builds hold a minimum frame (34 words with the preamble; 30 with the hardware preamble).

Engine 0's buffer is a one-port memory (`src/fifo_mem.v`) behind an arbiter and a head register: a 10-bit write pointer,
a 10-bit read pointer, an 11-bit count and a head-valid flip-flop (6-bit pointers at 64 words). A host push writes the memory and has the port; on a
clock without a push, an empty or departing head is refilled from the memory. PULL and the serialiser take the head.
The head word is captured into a 16-bit register on the clock after each read, so it does not depend on the memory
output holding between reads. In full duplex the same memory is split into a 512-word transmit ring and a 512-word
receive ring (16 + 48 at 64 words), each with its own pointers, count and head register. Exact timing: `docs/isa.md`, "Engine 0's TX FIFO"
and "Receiver and full duplex".

## Memory

Every memory is one port and reads on the clock, like IHP's SRAM block, whichever cells build it:

- `src/prog_mem.v`: each engine's program store, 32 x 16.
- `src/fifo_mem.v`: engine 0's buffer, 1024 x 16 (64 x 16 on the FPGA serialiser builds).

By default both are flip-flops. With `+define+USE_SRAM` each is IHP's single-port block **`RM_IHPSG13_1P_64x16_c2`**
(64 words x 16 bits, 236.80 x 64.36 um = 15,240 um2, one-cycle read, `A_DLY` tied high; the program store uses 32 of its
64 words); engine 0's 1024-word buffer is **`RM_IHPSG13_1P_1024x16_c2_bm_bist`** (236.80 x 336.46 um = 79,675 um2,
its write mask tied to all ones and its test port unused). The engine presents the next instruction's address every clock, so the clocked read is invisible to
programs (`docs/isa.md`, "Program memory"). The Tiny Tapeout build defines `USE_SRAM` and carries five macros: one
program store per engine and engine 0's buffer. The FPGA builds use flip-flops.

Area per engine (v0.2 engine, Yosys synthesis with IHP sg13g2 cells, typical corner, before place and route):

| Program store | Engine logic | Memory | Total per engine |
|---|---|---|---|
| flip-flops (default) | | in the logic | 98,351 um2 |
| `RM_IHPSG13_1P_64x16_c2` | 56,123 um2 | 15,240 um2 | 71,363 um2 |

Both builds match the Python model clock for clock (`python model/cosim.py`, with `USE_SRAM=1` for the block, which uses
IHP's own behavioural model of it). The macro integration in the Tiny Tapeout repository (`src/config.json`: the macro
block, the power stripes run across the macros' supply columns, KLayout DRC with the CMOS5L deck) follows Ken Pettit's
public walkthrough for his entry (github.com/kdp1965/ihp-um-janestreet-prism) and J.L. Nuijens's configuration
(github.com/JLNuijens/ttihp-cpu-1-1-uart).

## Verification

- **Python model** (`model/engine.py`), written from `docs/isa.md`, is the reference. `model/asm.py` assembles the
  programs.
- **Side-by-side random test** (`python model/cosim.py <tests> <clocks per test> <seed>`, test bench `test/tb_cosim.v`): the
  Verilog engine and the model run the same random programs, settings and pin stimulus and are compared on every clock;
  `USE_SRAM=1` runs it with the IHP block's model. `model/cosim_filter.py` (`test/tb_filter.v`) does the same for the
  glitch filter.
- **Protocol tests against modelled other ends** (`model/test_*.py`): I2C (with `model/i2c_slave.py`, including clock
  stretching), SPI (`model/spi_slave.py`), UART receive, pulse measurement, keypad, NEC infrared receive and transmit,
  DALI, the serialiser, receive and full duplex, and the blind identification of unknown lines from measured pulses.
- **Whole-chip test** (`bash test/run_chip.sh`, test bench `test/tb_chip.v` generated by `test/gen_chip_test.py`): the
  host port driven over SPI, every register, programs running on the pins, a value in every setting register of every
  slot and one past the last read back. Options: `NENG`, `SER0`, `CRC`, `TXDEPTH0` for each build, and `LATE=1` for a
  host that samples MISO late in the bit.
- **Planted bugs**: each new test is checked by planting a bug (`CHIP_SRC_OVERRIDE=file.v=replacement.v` for the
  whole-chip test) and confirming the test fails.
- **FPGA boards** against real devices: `docs/bench_wiring.md`.
- **Tiny Tapeout repository**: the cocotb test on RTL and on the gate-level netlist, and the precheck.
