# Protocol emulator ASIC

Our entry for Jane Street's protocol emulator ASIC competition
(https://blog.janestreet.com/protocol-emulator-asic-competition/).

- Process: IHP 130 nm CMOS5L via Tiny Tapeout, 6x4 tiles (about 24K logic cells)
- Must do: UART, SPI, I2C in firmware on a small programmable core
- Stretch: low-speed USB, 10 Mbit Ethernet; also CAN, PS/2, JTAG, SWD
- Deadline: 18 January 2027 (target shuttle: March 2027)
- Team: Mark Stanners + Claude

## Layout

- `src/`  Verilog design
- `test/` test benches
- `docs/` notes and design decisions (`core_design.md` the blocks, `isa.md` the exact instruction rules)
- `model/` Python reference: assembler (`asm.py`) and clock-by-clock engine model (`engine.py`)
- `programs/` engine programs in our assembly language
- `fpga/go_board/` bench tests on the Nandland Go Board

## Run the tests

Tools: OSS CAD Suite 2026-11-02, unpacked at `D:\Tools\oss-cad-suite`
(Icarus Verilog, Verilator, Yosys, nextpnr, GTKWave). From Git Bash:

    ./run.sh test     # simulate every test bench, prints PASS/FAIL
    ./run.sh size     # rough cell count per module
    python model/compare_uart.py   # model running programs/uart_tx.asm vs uart_tx.v, every clock
    python model/test_measure.py   # TIME stopwatch measuring a UART bit time
    python model/cosim.py 1000 400 11   # Verilog engine vs model: 1000 random programs x 400 clocks, every clock
    USE_SRAM=1 python model/cosim.py    # same, with IHP's SRAM block as program memory
    bash test/run_chip.sh               # whole chip, end to end, driven only through the SPI host port
    D:/Tools/oss-cad-suite/bin/gtkwave build/uart_tx.vcd   # look at the waveform

## Roadmap (11 weeks to 18 Jan 2027)

| Weeks | Stage | Done when |
|---|---|---|
| 1 (done 2 Nov) | Paper design: block diagram + instruction set (`docs/core_design.md`) | Mark has checked it and the open questions are settled |
| 2 (done 2 Nov) | Python model of the core: runs our firmware exactly, clock by clock | UART TX firmware runs on the model and matches `uart_tx.v` bit for bit |
| 3-4 (first pass done 2 Nov) | Verilog core, tested against the Python model cycle by cycle | thousands of random programs agree between model and Verilog |
| 4-5 | Firmware: UART TX/RX, SPI, I2C, each with a model partner device | all three pass, plus the measuring features |
| 6-7 | Into the Tiny Tapeout template; synthesis and layout on GitHub; fit 6x4, meet timing | clean build, timing met with margin |
| 7-8 | FPGA on the bench, talking to real boards (ESP32/Arduino as the other end) | real UART, I2C and SPI traffic with a real device |
| 9 | Stretch: CAN or PS/2 or low-speed USB; tidy the docs | |
| 10 | Submit early (aim for 11 Jan, a week of slack) | |

Other work comes first; this fills the gaps.

## Progress

- 2 Nov 2026: fixed-function UART transmitter + self-checking test bench (the known-good reference).
  PASS on 46 bytes at two baud rates. Checked the test can fail: a broken stop bit and a
  bit time one clock short were both caught. Size: 123 cells (31 flip-flops), about 0.5% of the budget.
- 2 Nov 2026: bench board found: **Nandland Go Board** (iCE40 HX1K VQ100, 25 MHz, 1280 logic cells,
  16 block RAMs, USB serial on the same lead). `fpga/go_board/`: hello test sends
  "Hello from Gosforth Skies" at 115200 once a second (hold switch 1 for nonstop). Simulated: the decoded
  line is correct. Built: 149/1280 cells (11%), timing good to 124 MHz.
  **Flashed and working on the real board:** 5 s on COM5 = 5 clean lines, 135 characters, no errors.
  Nonstop test (switch 1 held, back-to-back bytes): 115,804 characters, 4,288 complete lines, all correct.
  (Scripts: `flash.ps1`, `listen.ps1`, `check_driver.ps1`; run them from an ordinary PowerShell window.)
  Note: the whole two-engine chip won't fit a 1K part; the board tests one engine at a time.

## Flashing the Go Board (first time only)

iceprog/openFPGALoader talk to the board's FTDI chip through libusb, so on Windows
interface 0 of the "Dual RS232-HS" device needs the WinUSB driver (Zadig does this).
Leave interface 1 alone: that's the serial port we read the output on.
That's a driver change on the PC, so Mark does it himself. Then:

    fpga/go_board/build.sh prog
    # serial terminal (PuTTY etc.) on the board's COM port, 115200 8N1
- 2 Nov 2026: design questions settled (two engines, 16-bit registers, measuring as the headline, SPI host port).
  Exact instruction rules written (`docs/isa.md` v0.1; each engine has its own 32-word program memory;
  side-set made optional with an enable bit, as the UART program needs it).
- 2 Nov 2026: **Python model working.** `programs/uart_tx.asm` on the model matches `uart_tx.v` on every frame,
  sample by sample, at 8/16/32/88 clocks per bit (64 bytes each). The model runs back-to-back at the ideal
  10 bits per byte; the Verilog test bench leaves 2 clocks between bytes (its handshake). Two planted program
  bugs were both caught. TIME stopwatch measures a 'U' start bit exactly (8 to 1000 clocks, including a sender
  2.8% slow). Found on the way: the input synchroniser reads low for 2 clocks after reset; programs wait for
  idle-high first (noted in isa.md).
- 2 Nov 2026: **Verilog engine written** (`src/engine.v`, one engine, from isa.md). Spec tightened first:
  host/FIFO timing (everything decided from the state at the start of a clock) and every reserved encoding defined.
  **Side-by-side test** (`model/cosim.py` + `test/tb_cosim.v`): random programs (half fully random words),
  random configs, random pin activity and host traffic, full engine state compared every clock.
  5 x 1000 programs x 400 clocks = **2,000,000 clocks, all identical**. Five planted Verilog bugs were all caught
  (stopwatch capture was the weakest, so the generator now uses TIME more often: 3 -> 19 tests catching it).
  Size: one engine = 7,072 generic gates (about 900 flip-flops, 640 of them program memory and FIFOs).
  Two engines plus host port and filters: roughly 17K of the ~24K budget; it fits, but trimming is worth doing.
  On the Go Board (iCE40 HX1K): 2,784 LUTs against 1,280, so **one full engine does not fit the HX1K**.
  Options: a cut-down bench build (fewer pins/features), or the bigger FPGA Mark is looking for.
  Next: trim (one shared pin writer instead of several 32-bit rotators, pin space 32 -> 20), then the host port.
- 2 Nov 2026: Ada-style range checks added to the model (Mark's suggestion): after every clock each register
  is checked against its declared range (e.g. counts 0..16, words 0..65535) and the model stops dead if one strays.
  All model tests plus 1.2M more random clocks pass with the checks on; no register ever left its range.
- 2 Nov 2026: **trim, round 1.** Measured first, by removing one part at a time: pin writing (several 32-pin
  rotators) cost ~2,090 gates, program memory ~1,450, the IN/OUT shifters ~910, pin reading ~370, FIFO storage ~320.
  Only one instruction runs per step, so the engine now has **one** shared pin reader, **one** 32-bit shifter
  (serving IN and OUT, left and right) and **one** pin writer (plus the small side-set writer).
  Result: 7,168 -> **5,930 gates (-17%)**; iCE40 2,784 -> 2,245 LUTs (still too big for the HX1K's 1,280).
  Re-proved: 2,000,000 more random clocks identical to the model; three bugs planted in the new shared parts all caught.
  Further options (not done): pin space 32 -> 24 or 20 (a spec change), program memory in latches or SRAM,
  or a parameterised narrow bench build for the Go Board.
- 2 Nov 2026: **SRAM question** (Jane Street hint). IHP has a 64 x 16 SRAM block (15,240 um2). Real IHP-cell area
  of one engine: 99,091 um2, of which the flip-flop program memory is ~34,000. SRAM would save ~38K um2 chip-wide
  (~5 %) but needs a clocked-read redesign. Full chip estimate ~230K um2 of ~750K. Details and lean in
  `docs/memory_options.md`. (Earlier "24K cells" budgets were generic gate counts; um2 is the real measure now.)
- 2 Nov 2026: **engine made SRAM-ready** (Mark's call: settle the memory's behaviour before building on it).
  Program memory now reads on the clock (`src/prog_mem.v`), like IHP's SRAM; programs load only while stopped.
  Two builds, one switch: flip-flops (98,351 um2 per engine) or IHP's 64x16 SRAM block (71,363 um2 incl. the
  block). Both identical to the model on 1.2M random clocks (`USE_SRAM=1 python model/cosim.py` for the SRAM build);
  a planted fetch-timing bug caught in both. iCE40 unchanged: 2,246 LUTs.
- 2 Nov 2026: **host port and whole chip.** `docs/host_port.md` (SPI mode 0, command byte + 16-bit words,
  auto-incrementing bursts, per-engine registers, pin map); `src/host_spi.v`; `src/chip.v` (`protocol_chip`,
  Tiny Tapeout pins: two engines, settings registers, pin wiring, IRQ). On review, fixed a burst-read flaw before
  testing (a pre-fetch would have popped one FIFO word too many). **End-to-end test** (`test/run_chip.sh`),
  host side only: loads both engines over SPI; A sends "UHello!" as UART on uio[0]; B watches the same pin and
  **measures A's bit time from the 'U' (40 clocks, exact)**; settings read back; program writes while running
  ignored; FIFO reads pop exactly what they return (single and burst); pin conflict: A wins, stopping releases.
  Four planted bugs (pop-on-load, program write while running, MISO shifting early, pin priority) all caught;
  the pin-priority one was only caught after adding the conflict test.
  **Whole-chip area (IHP cells):** flip-flop memory 195,069 um2; SRAM build 109,870 + 2 x 15,240 = 140,350 um2.
  That is about 26 % / 19 % of the ~750K um2 allocation.
  Not yet: input glitch filters, Tiny Tapeout template/info.yaml, layout.
- 2 Nov 2026: **FPGA fit test for an iCE40 UP5K** (e.g. iCESugar v1.5), `fpga/up5k/up5k_top.v` (real two-way uio pins).
  The whole chip places and routes: 4,554 of 5,280 cells (86%), 2 of 30 RAM blocks, 26 of 39 pins,
  timing good to 15.4 MHz (passes at the iCESugar's 12 MHz; SPI host then up to 1.5 MHz).
- 2 Nov 2026: **segment 1 bench test ready** (host port on real hardware). `fpga/go_board/spi_test_top.v` wraps the
  unchanged `src/host_spi.v` with test registers, a loop-back FIFO, an ID register and a write counter;
  `esp32/spi_host_test` (compiles, ESP32 core 3.2.0) hammers it at 0.25-10 MHz. Simulation predicts it works
  to ~4.2 MHz and fails by 6.25 MHz (design spec: 3.1 MHz on the 25 MHz board). Wiring: PMOD 1 CS-GPIO5,
  2 MOSI-GPIO23, 3 MISO-GPIO19, 4 SCK-GPIO18, 5 GND-GND. Not yet run on the bench.
- 2 Nov 2026: **segment 1 on the bench: real SPI from an ESP32 into the host port on the Go Board.**
  First run (after a wiring slip: three ESP32 leads one pin along) showed a **real bug simulation had missed**:
  at 0.25-3 MHz about half the reads had the **last bit wrong** (A5C2 for A5C3), while 4-6 MHz passed.
  Cause: the ESP32 samples MISO late in the bit; the port loaded the next word just after a *rising* edge,
  so a late sampler saw the next word's first bit. The simulated host sampled exactly on the rising edge, so
  it never saw it. Fixed the usual way: reproduced it in simulation first (added a late-sampling host to both
  test benches), then made MISO change **only after falling edges**; both early and late hosts now pass in
  simulation, the whole-chip test passes both ways, and the original bug planted back is caught by the late host.
  **Bench after the fix, two runs: 0 errors in 15,372 checks from 0.25 to 4 MHz** (spec 3.1 MHz, so ~30 % margin);
  5-6 MHz fail by exactly one bit late (beyond the board's speed, as expected).
  Bench notes: the ESP32 (CH340 board) needed manual download mode (fixed later with a capacitor EN-GND: uploads now hands-free) and
  `esp32/upload_noreset.ps1`; moving the Go Board to another USB socket brings back the FTDI driver (re-run Zadig).
