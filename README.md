# Protocol emulator ASIC

A programmable protocol emulator chip for Jane Street's protocol emulator ASIC competition
(https://blog.janestreet.com/protocol-emulator-asic-competition/), on IHP's 130 nm SG13CMOS5L process through Tiny
Tapeout (6x4 tiles). Four small engines run serial protocols as firmware (UART, SPI, I2C, NEC infra-red, LED data and
more), time what they see on their pins, and are loaded and driven by a host microcontroller over an SPI port.
Engine A also has a bit-cell serialiser and receiver for Manchester and NRZ lines: 10 Mbit/s Ethernet frames, sent and
received, in full duplex.

Mark Stanners and Claude (Anthropic). The Tiny Tapeout project is
[ttihp-protocol-emulator](https://github.com/markstanners1-arch/ttihp-protocol-emulator) (datasheet in its
`docs/info.md`); its `src/` is a copy of this repository's `src/` plus the Tiny Tapeout wrapper and layout settings.

## The chip

| | |
|---|---|
| Engines | 4 (A-D), each with its own 32 x 16-bit program memory, 4-word FIFOs each way, registers x, y, osr, isr (16-bit) |
| Instruction set | 8 instructions after the RP2040 PIO (JMP, WAIT, IN, OUT, PUSH/PULL, MOV, SET, side-set, wrap) plus TIME, a 16-bit saturating stopwatch; WAIT with a timeout ([docs/isa.md](docs/isa.md)) |
| Clock | 40 MHz; each engine ticks every clkdiv + 1 clocks (25 ns to 1.64 ms) |
| Host port | SPI mode 0, SCK up to clk/8; 16-bit command `[15]` read, `[14:12]` engine, `[5:0]` register; bursts; IRQ output; ID register 0x2A reads 0x0024 ([docs/host_port.md](docs/host_port.md)) |
| Pins | 8 two-way (engine pins 0-7), 6 output-only (8-13), 5 input-only (15-19); the lowest-numbered engine driving a pin wins |
| Inputs | two-flip-flop synchroniser and a glitch filter on every input: a level must hold N + 1 ticks of 2^P clocks, from tens of ns to milliseconds ([docs/input_filter.md](docs/input_filter.md)) |
| Memory | IHP RM_IHPSG13_1P_64x16_c2 SRAM macros: one per engine for the program, one for engine A's 64-word transmit buffer; flip-flops on the FPGA builds |
| Engine A serialiser | NRZ or Manchester, optional differential pair, end marker, half-bit = SERDIV + 1 clocks (10 Mbit/s at SERDIV 1); a frame starts only when it is all in the buffer; underrun flagged. The host supplies the Ethernet FCS on the Tiny Tapeout build (the CRC-32 unit, `src/crc32.v`, is left out there) |
| Engine A receiver | Manchester decoder sampling the pin on both clock edges (a latch in the wrapper holds the falling-edge sample); locks on the preamble and start-of-frame delimiter; raw mode; keyed, idle-only mode change: transmit, receive (64-word buffer) or full duplex (16-word transmit ring, 48-word receive ring, received words read from RXDATA 0x37); hardware preamble option |
| Process | IHP SG13CMOS5L 130 nm, Tiny Tapeout 6x4 tiles, die 1289.28 x 710.64 um |

## Layout

| Build | Cells | Utilisation | Setup slack (slow corner) | Hold slack (fast corner) | Checks |
|---|---|---|---|---|---|
| Tiny Tapeout main: four engines, serialiser | 24,785 + 5 SRAM macros | 44.9 % | +6.39 ns | +0.145 ns | DRC, LVS, antenna 0; gate-level test and precheck pass |
| With the receiver and full duplex (TT branch `rx-duplex`; local LibreLane run) | 25,457 + 5 SRAM macros | 46.5 % | +7.08 ns | +0.151 ns | route DRC, KLayout DRC, LVS, antenna 0; gate-level test pass |

The local LibreLane flow (WSL Ubuntu, LibreLane 3.1.0.dev4, the Tiny Tapeout support tools) reproduces GitHub's runs
metric for metric.

## Programs

Engine programs in `programs/` (our assembly language, `model/asm.py`). "Bench" means run on an FPGA build of the chip
against real devices; "model" means proven on the Python model only.

| Program | Words | What it does | Proven |
|---|---|---|---|
| `uart_tx` | 5 | UART 8N1 transmit | bench |
| `uart_rx` | 13 | UART 8N1 receive, stop bit reported | bench |
| `measure_baud` | 7 | times a start bit | bench |
| `measure_pulse`, `measure_high` | 6, 6 | time low or high pulses | bench |
| `i2c_master` | 19 | I2C master, open drain, clock stretching, one host word per START, byte or STOP | bench |
| `i2c_sniff` | 29 | passive I2C monitor | bench |
| `spi_master` | 14 | SPI mode 0 | bench |
| `keypad` | 16 | 4x4 keypad scanner with debounce | bench |
| `ir_nec`, `ir_tx` | 29, 31 | NEC infra-red decode; transmit with a 38 kHz carrier made in software | bench |
| `eth_tx`, `ser_tx` | 16, 5 | Ethernet frames with link pulses; one serialiser frame per count | bench |
| `read_pins`, `push_789` | 3, 10 | raw pin levels; pin isolation test | bench |
| `dali_tx`, `dali_rx` | 13, 26 | DALI control device, forward and backward frames | model |

Host scripts: `pico/` (MicroPython on a Raspberry Pi Pico 2, library `pico/chip_host.py`, including `identify.py`, which
listens to an unknown 3.3 V board, measures each wire's levels and pulses, classifies it (UART and its baud, I2C, SPI,
LED data and others) and pairs wires into buses) and `esp32/` (Arduino sketch
`chip_test`).

## Verification

- **Python model** (`model/engine.py`), written from `docs/isa.md`, is the reference. Model tests run each program
  against model partner devices (`model/i2c_slave.py`, `model/spi_slave.py`, simulated UART, keypad, infra-red,
  DALI and identification targets, and the serialiser's output decoded back): `model/test_*.py`.
- **Side-by-side random test**: `python model/cosim.py 1000 400 <seed>` runs 1000 random programs for 400 clocks on the
  Verilog and on the model and compares every pin and register on every clock; `USE_SRAM=1` uses IHP's SRAM model,
  `CRC=0` the Tiny Tapeout build, `RX_FOCUS=1` concentrates on the receiver and full duplex. Every change is run on both
  memories; the receive and full-duplex logic alone has run several million clocks, identical throughout.
- **Whole-chip test**: `bash test/run_chip.sh` drives the whole chip only through the SPI host port (programs loaded,
  UART, I2C, SPI, the serialiser's Ethernet frame decoded from the pins, receive and full duplex over a loopback wire);
  options `NENG=2|3|4`, `LATE=1` (the host samples late), `CRC=0`.
- **Planted bugs**: every new test is checked by planting a bug it should catch; all have been caught.
- **Gate level**: the Tiny Tapeout gate-level test runs on the routed netlist.

## Bench results

All on FPGA builds of the same `src/`, driven by an ESP32 or a Raspberry Pi Pico 2 through the SPI host port; each
result is a scripted sequence read back line by line. Wiring in [docs/bench_wiring.md](docs/bench_wiring.md).

| Board | Build | Tested | Result |
|---|---|---|---|
| Lattice MachXO3L Starter Kit | 2 engines, 12 MHz, ID 0x0022 | UART at 115200 / 57600 / 19200, engine B timing A's bits (104 / 208 / 624 clocks); glitch filter on and off; I2C master to an ESP32 and an Arduino UNO slave (clock stretching, repeated START) with engine B sniffing; AT24C256 EEPROM; I2C address scan; SPI to a 74HC595 (16 of 16 steps); 4x4 keypad; NEC remotes decoded; IR transmit loopback (6 of 6 frames, carrier 38.46 kHz); UART receive (256 values at 115200); baud measure 1200 to 460800 within 0.16 %; I2C sniffer at 100 and 400 kHz | PASS |
| Mojo v3 (Spartan-6 LX9) | 3 engines, 50 MHz, ID 0x0023 | Pico regression (UART, timing, IRQ, pins, filter) | PASS |
| Mojo v3 | serialiser build, 40 MHz, ID 0x0022 | Ethernet frames at 10 Mbit/s, Manchester, differential: 336,100 frames clean; frames captured with a logic analyser at 500 kbit/s and decoded, the FCS equal to zlib's CRC-32; blind identification of WS2811 LED data at 800 kbit/s; full duplex over a loopback wire: 10 Mbit/s with the hardware preamble, and a full Ethernet frame at 20 kbit/s with the host topping up the 16-word ring, every word received back; keyed mode rules | PASS |
| Cyclone IV EP4CE6 | 3 engines, 50 MHz, ID 0x0023 | ESP32 regression (UART, B timing A at 432 / 872 / 2608 clocks, IRQ, pins, filter) | PASS |
| Cyclone IV EP4CE6 | serialiser build, 40 MHz from the PLL, ID 0x0022 | ESP32 regression (344 / 696 / 2080 clocks) | PASS |
| Nandland Go Board (iCE40 HX1K) | single blocks | UART (115,804 characters, all correct); SPI host port, 0 errors in 15,372 checks from 0.25 to 4 MHz; switch-bounce meter | PASS |

Proven on the model only so far: the four-engine chip as a whole (no bench FPGA holds four), the SRAM macros (IHP's
behavioural model), receive-only mode, DALI, and the `pico/w25q.py`, `ds3231.py` and `mcp4725.py` device scripts.

## FPGA builds

| Board | Build | Size | Fmax |
|---|---|---|---|
| MachXO3L-6900C | 2 engines (`bash fpga/machxo3/build.sh`) | 5,953 LUTs (86 %) | 28.7 MHz |
| Cyclone IV EP4CE6 | 3 engines (`bash fpga/cyclone4/build.sh`) | 6,098 LEs (97 %) | 51.7 MHz |
| Cyclone IV EP4CE6 | serialiser, receiver, full duplex, 2 engines (`build.sh ser`) | 5,702 LEs (91 %) | 43.7 MHz |
| Mojo v3 (Spartan-6 LX9) | 3 engines | 4,242 LUTs (74 %) | 54.7 MHz |
| Mojo v3 | serialiser, receiver, full duplex, 2 engines, 40 MHz | 85 % of slices | 42.3 MHz |

Builds are loaded into the FPGA's RAM only (MachXO3L: `openFPGALoader -b machXO3SK file.bit`; Cyclone IV:
`quartus_pgm -m jtag`; Mojo: `python fpga/mojo/load.py <port> <bin>`).

## Repository

- `src/` Verilog design: `chip.v`, `cluster.v`, `engine.v`, `serialiser.v`, `receiver.v`, `crc32.v`, `host_spi.v`,
  `prog_mem.v`, `fifo_mem.v`, `glitch_filter.v`
- `model/` Python reference: assembler, engine model, partner device models, tests, `cosim.py`
- `test/` test benches: `tb_chip.v` (whole chip), `tb_cosim.v`; `test/wave/` a GTKWave view of a serialised frame
- `programs/` engine programs
- `pico/`, `esp32/` host scripts and sketches
- `fpga/` builds for the MachXO3L kit, Cyclone IV, Mojo v3 and Go Board
- `docs/` [core_design.md](docs/core_design.md) the blocks, [isa.md](docs/isa.md) the exact engine rules,
  [host_port.md](docs/host_port.md) the register map, [input_filter.md](docs/input_filter.md),
  [bench_wiring.md](docs/bench_wiring.md); `docs/layout/` synthesis reports and layout metrics

## Run the tests

Tools: OSS CAD Suite (Icarus Verilog, Verilator, Yosys, nextpnr, GTKWave). From Git Bash:

    ./run.sh test                        # every unit test bench, PASS/FAIL
    python model/cosim.py 1000 400 11    # Verilog against the model, every clock
    USE_SRAM=1 python model/cosim.py 1000 400 12
    bash test/run_chip.sh                # whole chip through the SPI host port
    LATE=1 bash test/run_chip.sh
    python model/test_receive.py         # receiver and full duplex on the model
    bash test/wave/run_ser_frame.sh      # record a frame for GTKWave (test/wave/ser_frame.gtkw)

## Credits

- The engine instruction set follows the Raspberry Pi RP2040's PIO.
- SRAM macro integration in the Tiny Tapeout flow follows Ken Pettit's walkthrough
  ([kdp1965/ihp-um-janestreet-prism](https://github.com/kdp1965/ihp-um-janestreet-prism)), including its timing-repair
  settings; the power-grid plugin (`librelane_plugin_sram_pdn.py`, `odb_stripes.py`) and `pdn_cfg.tcl` are J.L.
  Nuijens's, from [JLNuijens/ttihp-cpu-1-1-uart](https://github.com/JLNuijens/ttihp-cpu-1-1-uart) (Apache-2.0), unchanged.
- IHP's open PDK, the Tiny Tapeout template and LibreLane; OSS CAD Suite, Quartus Prime Lite, Xilinx ISE, sigrok /
  PulseView, MicroPython.
