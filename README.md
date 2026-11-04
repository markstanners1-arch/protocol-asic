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
- 2 Nov 2026: **input glitch filter** designed (`docs/input_filter.md`), modelled (`model/glitch_filter.py`) and built
  (`src/glitch_filter.v`): a new level must hold for N+1 filter ticks, one tick every 2^P clocks (20 ns to ~10 ms
  at 50 MHz with one design). Model vs Verilog identical on 300 random pulse trains (252K clocks x 4 inputs), and
  the spec's promise checked directly (short pulses never pass, long levels always do); two planted bugs caught.
  **Bench: switch-bounce meter on the Go Board** (`fpga/go_board/bounce_top.v` + `bounce_listen.ps1`, log in
  `bounce_log.csv`). Mark pressed switch 1 84 times across the settings:
  - The Go Board's buttons bounce rarely (5 of 84 events, 6 %), mostly on release: one extra pulse, spread over
    1 us to 1.5 ms.
  - Filter off: the bounce got through (3 edges). Filter on (any setting from ~82 us): every bouncy event came
    out as exactly 1 edge.
  - Filter delay matched the design on hardware, including the expected spread from the prescaler:
    ~82 us setting 77-81 us, ~655 us setting 615-654 us, ~2.6 ms setting 2,465-2,602 us, ~10.5 ms setting
    10,030-10,470 us (theory: between N x 2^P and (N+1) x 2^P clocks).
  - Conclusion for these switches: ~0.65 ms cleans every bounce seen, with a delay nobody would notice.
  - Not yet: the filter wired into `chip.v` with a host register; a worse switch (toggle or microswitch on the PMOD)
    to see a real bouncer.
- 2 Nov 2026: fit test for a Lattice MachXO3LF-6900 (if Mark's missing board is the MachXO3 kit): free tools
  (`synth_lattice -family xo3`, `nextpnr-machxo2`), whole chip routes at 68% of LUTs, 9% FFs, 30 MHz.
- 2 Nov 2026: **MachXO3L Starter Kit found and working with the free tools.** `openFPGALoader -b machXO3SK <bit>`
  loads the FPGA's volatile SRAM (never the one-time NVCM). IDCODE LCMXO3L-6900C. Hello test (`fpga/machxo3/`) loads and runs
  (LED changes), but the kit's USB serial link is **not connected from the factory**: the schematic marks the
  FT2232H channel B to FPGA A11/C11 path 'FOR FUTURE RS232 FUNCTION' through DNI 0-ohm resistors.
  Its I/O headers are unpopulated (holes only), so bench wiring needs headers soldered.
- 2 Nov 2026: **whole chip ready for the MachXO3L kit** (`fpga/machxo3/chip_mxo3.v` + `chip_mxo3.lpf`, header J4).
  68% of LUTs, 30 MHz (runs at the kit's 12 MHz). End-to-end chip test rerun through this exact board wrapper
  (`fpga/machxo3/tb_chip_mxo3.v`): PASS with early and late hosts (first attempt failed only because the test
  talked during the wrapper's 255-clock power-on reset). ESP32 whole-chip sketch `esp32/chip_test` (programs
  generated from the assembler by `esp32/make_programs_h.py`): loads both engines, A sends text as UART at
  115200/57600/19200, the ESP32 reads it off the pin, B measures A's bit time. Waiting on J4 headers.
- 2 Nov 2026 (evening): **THE WHOLE CHIP RUNS ON REAL HARDWARE.** MachXO3L kit + ESP32 host over SPI, 7 leads on J4.
  At 115,200 / 57,600 / 19,200 baud: settings written and read back correctly; engine A sent "UHello from the chip!"
  as real serial and the ESP32 received it exactly off the chip's pin; engine B measured engine A's bit time exactly
  (104 / 208 / 624 chip clocks = 115,385 / 57,692 / 19,231 baud); IRQ rose with the result and cleared when read.
  **PASS, 0 problems.** Getting there: (1) one lead (M14, MOSI) not making contact; (2) the first build read every
  setting back as 0. Narrowed down by running the proven Go Board SPI test on the kit (0 errors to 2 MHz: pins and
  host port fine), which pointed inside the big build: the free MachXO tools' **LUT RAM** mapping (setting registers,
  FIFOs, program memory) is broken on hardware. Rebuilt with `-nolutram`: passes. `fpga/machxo3/build.sh` now always
  uses -nolutram. The Go Board SPI test also passes on the kit (0.25-2 MHz, 0 errors).
- 2 Nov 2026 (late): **glitch filter wired into the chip.** Every engine input (pins 0-7, 15-19) now passes a 2-FF
  synchroniser and the filter; chip-wide host register 0x29 FILTER ([3:0] N, [7:4] P). New program
  `programs/measure_pulse.asm` times low pulses. Whole-chip test (early and late hosts): filter off measures a
  30-clock glitch and a 200-clock pulse exactly; with a 64-clock hold the glitch vanishes and the pulse still
  measures 200. Planted bypass caught. MachXO3 build includes it.
- 2 Nov 2026 (late): **Tiny Tapeout repo** `markstanners1-arch/ttihp-protocol-emulator` (private, from the IHP
  template, CMOS5L, 6x4 tiles, 50 MHz, top `tt_um_gosforth_protocol_emu`, cocotb pin-level test). First layout
  run started (without the filter; the filter goes in after the baseline result).
- 2 Nov 2026 (late): MachXO3 build with the filter broke the engines' pins on hardware (no UART out, nothing
  measured) while the previous build still passed on the same bench. Cause: the free MachXO tools had put the
  program memories into **block RAM (DP8KC)**, another unreliable mapping. Built with `-nolutram -nobram`
  (84 % of LUTs): UART at 3 speeds and engine B's measurements pass again on hardware, and the synthesised netlist
  passes the end-to-end test in gate-level simulation (yosys cell models). `build.sh` now uses both flags.
  Hardware filter test: G15 pulses (ESP32 GPIO 17) never seen by any build yet; lead being checked.
- 2 Nov 2026 (late): **glitch filter proven on real hardware** (MachXO3L, no-RAM build). The ESP32 drives engine
  pin 15 (G15) from GPIO 17. Pin levels read correctly; filter off: a "2 us" glitch measured 2.7 us and a "20 us"
  pulse 21.1 us (the chip measured the ESP32's own pin-switching overhead, ~0.7 us); filter on (5.3 us hold): the
  glitch vanished, the pulse still measured 21.0 us. **Whole hardware test PASS, 0 problems.**
  On the way: the G15 lead was in G16, then F15 (a raw pin-level diagnostic, `programs/read_pins.asm`, showed
  exactly which pin it was on); and the ESP32's Serial2 had claimed GPIO 17 as its default TX pin (sketch fixed).
- 2 Nov 2026 (late): **Cyclone IV build ready** (`fpga/cyclone4/`, Quartus Prime Lite 25.1 from the command line,
  `bash fpga/cyclone4/build.sh`, then `load` for the USB Blaster; JTAG into SRAM only). The same `src/chip.v` fits an
  EP4CE6E22C8 at 4,496 of 6,272 logic elements (72 %), and Quartus puts both program memories into M9K block RAM
  (2 of 30), which the free MachXO tools could not do reliably. Timing at 50 MHz, the ASIC's own clock: Fmax 53.9 MHz
  on the slowest grade at 85 C, 1.4 ns slack. The worst path is program memory read -> instruction decode -> shared
  pin writer -> output register; yosys's longest-path count on the IHP netlist points at the same chain (52 generic
  gate levels through the TIME result and the pin writer's rotate), so that is the path to read first in the layout
  timing. Pin locations are still TODO in `chip_c4.qsf` (board arrives 3 Nov). `esp32/chip_test` now takes the chip
  clock from one setting (`CHIP_HZ`: 12 MHz kit or 50 MHz Cyclone), deriving the SPI speed and the filter hold from it.
- 2 Nov 2026 (late): **I2C master and SPI master programs, each proven against a model partner device.**
  Both use the same trick: the host sends one 16-bit command word per action whose top 5 bits are the routine's
  address (from the assembler's labels), and the program jumps there with `out pc, 5`, so START, send, receive,
  STOP (I2C) or select, transfer, deselect (SPI) each cost the host one word and the program stays small (30 and 14
  words). `programs/i2c_master.asm`: SDA open drain through pin directions, SCL on side-set, 10 ticks per bit with
  every SCL high and low at least 5 ticks (the standard's 4.7/4.0 us at 100 kHz hold); reports every ACK bit.
  `model/i2c_slave.py` is a register-pointer slave (like most sensors and EEPROMs); `model/test_i2c.py` writes 4 bytes,
  reads them back with a repeated START, addresses a missing device (NAK reported), and checks every SCL high/low
  time, at three clock dividers: PASS. Two planted bugs (data bits not inverted; ACK sampled at the wrong edge) both
  caught. `programs/spi_master.asm` (mode 0, MSB first, 6 ticks per bit) with `model/spi_slave.py` (command byte =
  read/write + address, then data) and `model/test_spi.py`: PASS at three dividers; planted bugs (MISO sampled on the
  wrong edge; CS driven before its idle level was set, a real slip the test found) both caught. The labels are exported
  to `esp32/chip_test/programs.h` for the bench. Not yet: the ESP32 as an I2C/SPI slave on the bench, a real I2C part,
  and engine B watching the bus (sniffer programs: the measuring headline).
- 2 Nov 2026 (late): **I2C on the whole chip, with engine B watching the bus.** `programs/i2c_sniff.asm` (27 words):
  samples SDA on every SCL rise, then polls both pins until SCL falls; SDA moving while SCL is high is a START or
  STOP and resyncs the byte (a first version that just counted 9 clocks per byte drifted, because STOP and repeated
  START each carry a data-less SCL rise). It reports each byte with its ACK bit. Proven on the model alongside the
  master and slave (every byte, every ACK/NAK, repeated START included); it needs an SCL period of at least 20 of its
  ticks. Then in the whole-chip test (`test/tb_chip.v`, early and late hosts): engine A runs the I2C master on
  uio[0]/uio[1], engine B watches the same pins, and a few lines of bench Verilog play a slave that ACKs. The chip's
  pins idle right (SCL driven high, SDA released), A reports both ACKs, B reports both bytes. Two planted bugs
  (master data bits not inverted; watcher on the wrong pin) caught. Two things found on the way: the bench slave must
  count SCL *rises* (the fall inside START is not a data clock), and the filter test before it left a 64-clock hold
  that swallowed every 20-clock I2C edge, so the I2C section resets FILTER first. A real host must remember the same.
- 2 Nov 2026 (late): **ISA v0.2: `side_dir`** (Mark's call). One config bit (MISC bit 13): when set, side-set writes
  the side pins' *directions* instead of their levels, so a bus line can be open drain (side 1 = pull low, 0 = let go)
  from the side-set, which costs no instruction. Why: the ESP32 as an I2C slave stretches the clock, and a push-pull
  SCL would fight it electrically. Proven three ways: model and Verilog identical on 400,000 random clocks with the
  bit randomised (plus 120,000 with the SRAM build); a planted Verilog bug ignoring the bit was caught in 71 of 200
  programs; whole-chip test both host timings. Assembler: `.side_set 1 opt pindirs`.
  **I2C master rewritten open drain on both lines, honouring clock stretching**: after every SCL release it waits
  for SCL to really be high (`wait 1, rel 31`: the pin below SDA, so the pair sits anywhere). Model test: the slave
  now stretches SCL for 7 and 300 clocks after every ACK, every byte still right; the whole-chip bench slave stretches
  90 clocks mid-byte and after each ACK. A planted master that ignores stretching is caught by both (the chip test
  only once the bench stretched *mid-byte*: after an ACK the master was already waiting for the slow SPI host, so the
  stretch never overlapped it; a test that cannot fail is not a test). Use clkdiv >= 2 for exact 10-tick bits (the
  2-clock synchroniser delays the engine's view of its own release by a tick below that). The bench UART monitor is
  now switched off once uio[0] is reused for SCL. `src/` recopied to the Tiny Tapeout repo (push held until the two
  running layout jobs report, so the baseline numbers are from the v0.1 engine).
- 2 Nov 2026 (late): **v0.2 engine on real hardware: PASS, 0 problems** (MachXO3L kit rebuilt, 26 MHz, loaded into
  SRAM; `esp32/chip_test` rerun: UART at 115200/57600/19200, B's bit-time measurements, pin diagnostic, glitch
  filter all as before). Cyclone IV rebuilt too: 72 %, Fmax 51.8 MHz, still above 50. `esp32/chip_test` has a new
  on-demand I2C test (send `i` on the Serial Monitor): engine A master at 10 kHz on engine pins 2/3, engine B
  watching, the **ESP32 as the I2C slave** at 0x50 (Wire slave mode; it stretches SCL in its interrupt handler, so
  this is the stretching test on real wires). Needs two more leads, J4-10 (M16) -> GPIO 22 (SCL) and J4-13 (L15) ->
  GPIO 21 (SDA), plus 4.7 k pull-ups to 3.3 V. Compiles; **not yet run** (leads not fitted).
- 2 Nov 2026 (late): **FIRST LAYOUT RESULT (Tiny Tapeout flow, IHP SG13 CMOS5L, 6x4 tiles), from the v0.1 engine with the
  filter, commit 4017063 of the TT repo.** The gds job completed and published the GDS after about 1 h 40 min; then **precheck PASSED (24 min 47 s, the
  foundry's KLayout rule deck included) and the gate-level cocotb test PASSED**; only the viewer job failed, because GitHub Pages
  is not available on a private repo (it will work once the repo is public, as submission requires). They were still running at 23:20 (a watcher's exit code, really GitHub's API rate limit
  after 90 minutes of polling, was first misread as a failure: lesson, don't poll `gh run watch` for hours). Numbers (`docs/layout/`):
  - **Fits easily**: 19,765 standard cells, 302,319 um2, **33.5 % of the 902K um2 core** (die 1289 x 711 um). Of that,
    2,043 flip-flops (100K um2) and 3,155 timing-repair buffers (42K um2, 2,107 of them hold buffers).
  - **Timing met at 50 MHz at all three corners** (fast -40 C, typical, slow 125 C): setup and hold slack 0 ns worst
    negative, total negative 0. Clock skew about 0.4 ns.
  - **Clean**: DRC 0, LVS 0 differences, antenna 0 violating nets, power grid 0, detailed routing converged (0 DRC
    errors after 8 iterations). Warnings only: 147 nets over the max-fanout limit (the program-write data and reset
    fan out to every flop; the resizer buffered them and timing passes) and 9 slew violations at the slow corner.
  - Synthesis in the flow: 16,184 cells, 253K um2 (our local yosys estimate was 202K: different ABC script).
  So: there is room for the v0.2 engine, the SRAM build, and more. The v0.2 layout run starts when the TT repo is pushed.
- 2 Nov 2026 (late): **I2C ON REAL WIRES: PASS, 0 problems.** MachXO3L kit (v0.2 engine) + ESP32 as the I2C slave at
  0x50 on engine pins 2/3 (J4-10, J4-13 -> GPIO 22/21, 5.1 k pull-ups to 3.3 V), 10 kHz. Engine A wrote 4 bytes into
  the ESP32's registers (every ACK reported 0, the ESP32 holds A5 3C 00 FF), read them back, got the NAK from an
  empty address, and **engine B watching the same two wires reported every byte and ACK bit on the bus**, 13 bytes,
  all right. First run failed on the read-back only: the watcher showed the ESP32 itself put 0xCB then 0xFF on the
  wire, so our master read faithfully what it was given. Cause: the original ESP32's I2C slave hardware cannot stretch
  the clock, so its callback could not load the reply in time (the S2/S3/C3 parts can). Fix on the ESP32 side: load
  the reply when the pointer write arrives (`Wire.slaveWrite`), and read as pointer-write, STOP, fresh START. So the
  stretching test on wires still needs a stretching slave (an S3, or the UNO); the chip side is proven in simulation.
  Run it with `esp32/rerun.ps1 -Cmd i`.
- 3 Nov 2026 (00:30): **I2C with clock stretching on real wires: PASS, 0 problems.** An Arduino UNO R3 (ATmega328P,
  `arduino/i2c_slave_nano`, same register-pointer device as the model slave, its 5 V pull-ups switched off so it only
  pulls low on our 3.3 V bus) as the slave on the same two wires; the ESP32's own I2C off (`rerun.ps1 -Cmd n`).
  The AVR holds SCL low while its handler queues the reply, and the master waited for it: 4 bytes written, read back
  with STOP-then-START **and with a repeated START**, every ACK right, engine B reporting all 20 bytes on the bus. Two
  slips on the way, both on the bench side: the FPGA was not plugged in (the watcher showed the master's bytes on the
  wire with no ACKs, so the chip was fine and nobody was listening), and the AVR Wire library calls the request handler
  once per read, so it must queue all 4 bytes. The test's last data byte is now 0x7E, not 0xFF, because an unanswered
  read reads as 0xFF and a byte that cannot fail is no test. Do not run the ESP32-as-slave test (`-Cmd i`) with the UNO
  connected: both answer at 0x50. Not needed after all: level shifting (the 328's I2C inputs were read as the
  datasheet's 0.7 Vcc = 3.5 V threshold, but 3.3 V worked on this board).
- 3 Nov 2026 (00:50, stopping for the night): **SPI to a 74HC595 on the bench, not yet working**: engine A drives SCK /
  MOSI / latch on engine pins 4/5/7 (J4-14/15/17) and reads the 595's QH' on pin 6 (J4-16); engine B confirms SCK
  (60-clock lows at 100 kHz). The LEDs on the 595 stayed dark and MISO read 0, with one lead found in the wrong hole
  (J4-14 was in 13) and still dark after. Next: meter the 595's VCC (16) = 3.3 V, GND (8) = 0, OE (13) = 0, SRCLR (10)
  = 3.3 V, then QA (15) after a run (ends on 0x55, so QA = 1); then the QH' lead. Test: `esp32/rerun.ps1 -Cmd s`.
  The v0.2 layout run (TT repo commit 4258d90) was still in its build step at 00:50; read it first thing
  (`gh run view 41543287970 -R markstanners1-arch/ttihp-protocol-emulator`, one call, no watching).
- 3 Nov 2026 (morning): **Specs reread, the "32-word pinch" measured, and the I2C master cut from 30 words to 19.**
  Send and receive were the same nine SCL clocks with different levels on SDA, so one routine (`xfer`) now takes the
  nine SDA levels from the host's word (the byte, then the ACK slot) and pushes back the nine levels seen on the wire
  as byte << 1 | ACK bit, the sniffer's format. Command words: `start << 11`, `xfer << 11 | byte << 3 | ack << 2`
  (send: ack = 1, the slot released; read: byte = 0xFF, ack = 0 to ACK, 1 to NAK), `stop << 11`; labels 12, 3, 15.
  Bonus: a sent byte comes back as it went on the wire, so a mismatch means another master pulled SDA low
  (arbitration lost); `model/test_i2c.py` checks this by jamming SDA during a send (reads back 0x00). Proven: model
  test at dividers 2/4/49 with and without stretching, cosim 400K clocks on both memory builds (engine unchanged),
  whole-chip test LATE=0/1, ESP32 sketch compiles (not yet run: the bench is being rebuilt from scratch today, and the
  Cyclone IV board arrives). Planted bug (eight clocks instead of nine) caught by both the model and the chip test.
  Verdict on the pinch: by the PIO yardstick (32 instructions shared by four state machines) 32 per engine is not
  short; the sniffer's 29 words are the lack of a "wait for pin change", not of words; checksums stay the host's job,
  as on PIO. 64 words (a 6-bit address: JMP loses a delay bit, WRAP splits) held in reserve. Four engines partly
  relieve it (split a job over two engines). Decision (Mark): **go to four engines next**; the engines already sit
  in a generate loop in `src/chip.v`, so the work is the host port's engine addressing (a two-byte command), the
  pin priority chain, tests, docs and a layout run.
- 3 Nov 2026 (afternoon): **Four engines.** `protocol_chip` takes `NENG` (default 4; the MachXO3L and Cyclone tops pass 2,
  since neither board fits four: 84 % and 72 % full with two). Host port v0.2 (`docs/host_port.md`): the command is now
  16 bits, `[15] read, [14:12] engine, [5:0] register` (register numbers unchanged; one more byte per transaction);
  new chip-wide read-only register 0x2A ID = `[7:4]` spec version 2, `[3:0]` number of engines, so a host can ask;
  an engine number past the last is ignored on write and reads 0; the lowest-numbered engine driving a pin wins
  (A > B > C > D, a chain in `src/chip.v`); IRQ = any engine's RX FIFO non-empty. The engine itself is untouched (cosim
  400K clocks both memories, unchanged). `test/tb_chip.v` takes `NENG` (`NENG=2 bash test/run_chip.sh`), converts every
  command to the two-byte form, and adds: ID register through any engine number, engine C running push_789 with the
  IRQ, the priority chain with D low / C high / A low, and writes to engine 5 ignored. PASS for NENG=4 and NENG=2,
  LATE=0/1. Planted bugs caught: the chain the wrong way round (highest wins), and the engine field taken from the
  wrong command bits. ESP32 sketch converted (`cmd()` two bytes, `ENG_C/D`, ID check at the top of the regression) and
  compiles; **not yet run on hardware** (bench being rebuilt). FPGA builds with two engines: MachXO3L 30.9 MHz
  (PASS at 12), Cyclone IV 4,461 LEs (71 %), Fmax 53.56 MHz. TT repo commit 2d2a76c (sources, cocotb test with the
  16-bit command, info.yaml/info.md "four engines"): **cocotb test PASS on GitHub**; gds run 41642156659 started 13:11,
  to be read with one `gh run view` after ~15:30. The v0.2 two-engine layout (run 41543287970, read this morning):
  20,448 cells, 306,341 um2, 33.9 % utilisation, setup/hold slack 0.0 at all three corners, DRC 0, LVS 0, antenna 0
  (24 slew and 156 max-fanout warnings at the slow corner, as before). Pins are the budget now: 20 shared by four
  engines, about five each.
- 3 Nov 2026 (14:00): **first four-engine layout failed in placement**, not for want of area but for the flow's default
  placement density target. Synthesis: 552,741 um2 for four engines (61 % of the 902K core; two engines were 253K,
  so the pin chain and host mux cost a little over the doubled engines). OpenROAD reported 66.7 % utilisation, the
  Tiny Tapeout config's `PL_TARGET_DENSITY_PCT` of 60 was "too low", the placer's own target came out at 1.007 and
  detailed placement failed on 8 instances (GDS run 41642156659, 6m53s; precheck and gl_test skipped). The config's
  own comment says to raise the target, up to 80 reported working: set to 80 (TT commit ac6fb72), second run started
  13:26 (run 41644302624). If that fails too: the SRAM program memory (saves ~27K um2 per engine, ~110K in all, taking four engines to
  about 49 %), or three engines (~46 %).
- 3 Nov 2026 (14:30): bench being rebuilt. After the USB replug the ESP32 moved from COM7 to COM12 (the three ESP32
  scripts now find the CH340 port themselves) and the kit's FT2232 came back on the FTDI serial driver, so
  openFPGALoader could not open it until Zadig put WinUSB on "USB Serial Converter A" again (same as the Go Board;
  expect this after any socket change). Kit loaded with today's two-engine build (`fpga/machxo3/build/chip.bit`),
  ESP32 uploaded with the two-byte-command sketch; with no J4 leads fitted yet the regression reads 0xFFFF everywhere,
  as an open MISO should. Cyclone IV board arriving within the hour; it has no pin assignments yet, so the kit stays
  the bench for today's hardware check of the new host port.
- 3 Nov 2026 (15:00): **host port v0.2 proven on real hardware.** Rebuilt bench, MachXO3L kit with the two-engine build,
  ESP32 regression PASS, 0 problems: ID 0x0022, two-byte commands, both engines, UART at three rates, glitch filter,
  IRQ. Three lead slips on the way, each diagnosed from the ESP32 side with new sketch commands: IRQ lead in GPIO 2
  instead of 4 (the regression's IRQ checks fail, all else passes); then CS/SCK/MOSI disturbed while moving it (all
  reads 0x0000, nothing received: `p` lead probe showed MISO and IRQ driven low by the chip, so the command was not
  arriving); then the MISO lead's J4 end in a hole held low (writes worked, engine A's UART heard, reads still 0).
  `p` = lead probe (pull-up/pull-down test of MISO and IRQ + raw ID read), `q` = IRQ held high 15 s, `l` = 30 s of
  repeating ID reads for the oscilloscope (Mark's Hantek DSO5102P came out; 6,000 of 6,000 reads 0x0022 once the
  MISO lead was home). Written into `docs/bench_wiring.md` / `.pdf` as "If it doesn't answer".
- 3 Nov 2026 (15:40): **second four-engine layout run failed the same way** (run 41644302624, density target 80): utilisation
  66.7 % after global placement, the placer's own target density 1.03 (limit 0.99), detailed placement failed on 7
  instances in the post-placement repair step. So the density knob was not the problem: four flip-flop-memory engines
  at 553K um2 (61 % of the 902K core) are too dense for this flow on IHP's cells, where two engines at 34 % placed with
  ease. Options, Mark's call: (1) three engines, about 45 %, a parameter change; (2) four engines with the IHP SRAM
  block for each program memory (~445K, 49 %, plus four 15K macros to place: the memory_options plan, a day or more,
  and the block's acceptance on CMOS5L is still unchecked); (3) slimmer engines (a 20- or 24-pin space instead of 32,
  shallower FIFOs). Started a **measurement run with three engines** (TT project.v `#(.NENG(3))`, density back to 60)
  so the decision has a number behind it. Lesson for the roadmap: keep the synthesised area under about half the core.
- 3 Nov 2026 (16:00): **I2C PASS on the rebuilt bench with the 19-word master** (one `xfer` routine) and the two-byte host
  port: ESP32 as the slave at 0x50, 4 bytes written and read back, engine B saw all 13 bytes, 0 problems. The bus
  wiring took three goes, each found from the ESP32 side without a meter (the meter had been tidied away): new sketch
  command `b` (I2C wire check: engine B reads all 20 engine pins raw while the ESP32 pulls its SDA, then its SCL, low,
  so the printout names the chip pin each lead reaches) and `k` (GPIO 22 held low for 30 s for a meter). Findings in
  order: both leads reaching no chip pin; SDA right, SCL reaching nothing; swapping the ESP32 ends proved both GPIOs
  good, so the kit end was wrong; it was in H16 (hole 25, an output-only pin) read as M16 (hole 10). Lesson for the
  sheet: the ball letters H/M are easy to confuse on the kit's silkscreen; the hole number is the safer label.
- 3 Nov 2026 (16:15): **I2C PASS with the UNO R3 as the slave** (clock stretching, STOP-then-START and repeated-START
  read-backs), first time after the leads moved over from the ESP32, 0 problems. The 19-word master has now done both
  slaves on real wires.
- 3 Nov 2026 (16:40): **SPI master to the 74HC595 PASS, 0 problems** (yesterday's dark LEDs were the bench, not the
  design: rebuilt per `docs/bench_wiring.md` section 3 with four LEDs on QA-QD it worked first time). Engine B times
  every SCK low at 60 clocks (100 kHz, clkdiv 19), each transfer returns the previous byte through QH'. New sketch
  command `w`: a slow LED walk (QA first, 0.7 s a step, twice round, all on, all off) with the QH' read-back printed;
  16 of 16 steps returned the byte before. So on the rebuilt bench, all with the two-byte host port: regression PASS,
  I2C PASS with both slaves, SPI PASS. Still to wire: nothing; next hardware is the Cyclone IV.
- 3 Nov 2026 (16:55): the 595's LEDs: the flat-topped ones from the drawer never light at 3.3 V (a red one did at once); with
  red/red/white/yellow fitted the walk (`-Cmd w`) chased as it should, white dim as expected. Noted on the wiring sheet.
- 3 Nov 2026 (17:20): **Cyclone IV board pinned.** It is the black EP4CE6E22C8N core board (USB-C power + CH340 serial,
  10-pin JTAG, 50 MHz oscillator on pin 24, serial 23/10, LEDs 1 2 3 7 11, bank jumpers VB/VC both at 3.3 V); the headers
  carry the FPGA pin numbers. `fpga/cyclone4/chip_c4.qsf` now places everything on the right-hand header 38-72 in
  silkscreen order (CS 38, SCK 39, MOSI 42, MISO 43, IRQ 44, uio 46-55, uo 58-66, ui 67-71, LEDs 1/2); build 4,466 LEs
  (71 %), Fmax 53.4 MHz, no pin complaints. `docs/bench_wiring.md` section 5 has the lead table. Not programmed yet:
  the board needs a USB Blaster on its JTAG header and there is none on the bench (the PC has the driver); ordered.
- 3 Nov 2026 (17:45): USB Blaster (Rev C clone, eBay seller digexx15, Leicester) ordered, due 5-6 Nov; the Cyclone build waits for it.
- 3 Nov 2026 (18:00): `test/tb_chip.v`'s multi-engine section now works for any engine count (`NENG=2|3|4 bash
  test/run_chip.sh`): the last engine runs push_789 with the IRQ, the priority chain is tested with the last engine
  low, the one below it high, then A low (for three or more engines), and the number past the last is checked. PASS at
  2, 3 and 4; the reversed-chain bug planted at 3 is caught. So whichever count the layout settles on is already proven.
- 3 Nov 2026 (18:15): **three engines fit the Cyclone IV board**: 6,273 cells wanted of 6,272 with Quartus's defaults
  (one over), 6,116 (98 %) with `OPTIMIZATION_TECHNIQUE AREA` and registers packed for area, Fmax 51.6 MHz, timing met
  at 50. `fpga/cyclone4/chip_c4.v` now builds three (`#(.NENG(3))`), the kit stays at two (84 % full already). So the
  three-engine chip can be run on real hardware at the ASIC's clock as soon as the Blaster arrives.
- 3 Nov 2026 (18:30): **on the list: a "what is this chip?" demo.** An unknown part on the bench: idle levels on all pins
  (read_pins), any pulse or period measured (stopwatch), an I2C address scan one word per address with the ACK bit as
  the answer (0x50 EEPROM, 0x68 RTC, 0x76 pressure...), the SPI JEDEC command 0x9F read off an unknown 8-pin device
  (flash answers with maker and part), then exact-timed talking once there is a guess. All on the existing i2c_master /
  spi_master / measure programs: it is a host-side script (ESP32 now, RP2040 MicroPython for the demo board later).
  Mark's hunch: this is likely what the brief is really after, given Jane Street's previous puzzle; the measuring
  headline made into a demo. Target: try it on the Cyclone with three engines once the Blaster is here (Fri 6 Nov).
- 3 Nov 2026 (18:45): **first piece of the "what is this chip?" demo: an I2C address scan** (`esp32/rerun.ps1 -Cmd a`):
  START, address + W, STOP for 0x08-0x77 with the existing i2c_master program at 100 kHz; the ACK bit in the reply says
  who answered, and a short table guesses the part from the address (0x50-57 EEPROM, 0x68 RTC/MPU6050, 0x76 BMP280,
  0x27/0x3F LCD backpack, 0x3C OLED, 0x48 ADC...). First run found the UNO slave at 0x50 and nothing else. Also a
  check that the address went out as sent (a bus held low shows up as a wrong read-back).
- 3 Nov 2026 (evening): **three engines lay out cleanly** (TT run 41665293508, commit f087b2d, density target 60):
  30,221 cells, 446,885 um2, **49.5 % utilisation**, setup and hold slack 0.0 at all three corners at 50 MHz, DRC 0,
  LVS 0, antenna 0 (49 slew and 224 fanout warnings at the slow corner, the usual kind), gate-level test PASS, 2h30m
  build. Stats in `docs/layout/metrics_3nov_v02_3eng.csv`. So the ladder is: two engines 34 % (clean), three 49.5 %
  (clean), four 61 % (fails detailed placement). Four would need the SRAM program memory (~49 %). Decision pending
  Mark: three as it stands, or SRAM for four. Note the TT repo's project.v is still at `#(.NENG(3))` from the
  measurement run; whichever way, the ProtocolASIC `src/chip.v` default (4) and the TT wrapper must agree before
  submission.
- 3 Nov 2026 (night): **decision (Mark): three engines.** `src/chip.v` default `NENG = 3`; tests, specs (`host_port.md`,
  `core_design.md`) and the sketch say three; the TT wrapper uses the chip default and its metadata says three (new gds
  run on the push, expected the same as the measurement run). Proven at three: cosim 400K clocks both memories, whole-chip
  test NENG=3 (LATE=0/1) and NENG=2. Hardware proof of three waits for the Blaster and the Cyclone.
- 3 Nov 2026 (late): **engine isolation proven** (Mark's question: does one engine failing hurt the others?). New section
  in `test/tb_chip.v`: A hangs on a WAIT that is never met (measure_pulse on an input held low; STATUS shows pc 0,
  running), B pushes 7/8/9 meanwhile, the last engine (three-engine builds) sends two UART bytes meanwhile, then A is
  stopped, reloaded and restarted through the host alone: A runs, B is still running with its third word still
  waiting, the last engine still running. PASS at NENG=3, 2, LATE=1. Two planted cross-couplings caught: every engine
  reset when A stops (caught in several places), and stopping any engine popping every RX FIFO (caught only by the new
  section). Same test in the sketch (`rerun.ps1 -Cmd x`, push_789 now exported to programs.h): **PASS on the kit**.
  Nothing joins the engines but the host's selector, the pin priority chain and the IRQ OR; the chip-wide glitch
  filter setting is the one shared knob.
- 3 Nov 2026 (late): **both repos made public** (Mark: "no need for secrecy"): markstanners1-arch/protocol-asic and
  ttihp-protocol-emulator, scanned first for credentials or personal data (none). GitHub Pages enabled on the TT repo
  (source: Actions), so the layout viewer job should now pass; it will publish at
  https://markstanners1-arch.github.io/ttihp-protocol-emulator/ after the next gds run (41697384154, the three-engine
  confirmation, in progress). Next open question for the Tiny Tapeout Discord: is IHP's RM_IHPSG13_1P_64x16_c2 SRAM
  block accepted on the CMOS5L shuttle? (Decides whether four engines is ever an option.)
- 3 Nov 2026 (23:30): **first oscilloscope captures of the chip on real wires** (`docs/bench/i2c_scope_1.png`, `_2.png`,
  Hantek DSO5102P, saved to a FAT32 stick: the scope's PC driver is Windows-7 era and Windows 11's core isolation
  refuses it; the scope's rear USB is no use without it). CH1 SCL, CH2 SDA, engine A as I2C master to the UNO slave at
  100 kHz, new sketch commands `o` (60 s of START 0xA0 0x03 0xA5 STOP every 20 ms) and `z` (the same until a key).
  The trace shows the address byte 1010 0000 = 0xA0 on nine clocks with the UNO's ACK low on the ninth, and the
  host-paced gaps either side (SCL held low while the master waits for the host's next command word, a few hundred
  us at the ESP32's 100 us polling): a faithful picture of a host-paced master. Scope hints kept: probes on breadboard
  rows beside the leads, trigger CH1 rising or SDA falling with holdoff ~1 ms to frame the START, 1 V/div, 20-50
  us/div. To check with cursors next time: one SCL period = 10 us. Also tonight: a 2010-2015 USB stick backed up to
  D:\USB stick backup 2010-2015 before it went in the scope.
- 3 Nov 2026 (23:45): scope cursors on one SCL period: **10.0 us**, i.e. 100 kHz as set (clkdiv 11 at 12 MHz, 10 ticks a bit); the chip's timing confirmed by an outside instrument for the first time.
- 3 Nov 2026 (23:55): three more captures (`docs/bench/i2c_scope_3..5.png`), cursors on. Picture 4 is the period:
  adjacent SCL rising edges, **dt 10.80 us** by the scope's cursors (Mark read 10.0 by eye earlier), i.e. 93-100 kHz
  against 100 nominal. The designed bit is 10 ticks of 1 us; the cursor is good to about half a microsecond at this
  zoom, and a bit can honestly be 11 ticks when the pull-up's rise (5.1 k into breadboard + two probes) plus the
  2-clock synchroniser pushes the "SCL seen high" past the tick boundary, as the program comment warns. To pin down:
  2 us/div and cursors on one period; and a 2.2 k pull-up would sharpen the rise. Pictures 3 and 5 are partial widths.
- 4 Nov 2026 (00:30): **a sketch bug found by the scope.** After the photo session the kit answered every read with
  0x0000 while writes worked (UART text arrived, IRQ followed), the afternoon's "MISO lead off" signature, but the
  leads were fine: CH2 on the MISO wire at GPIO 19 during the ID-read loop showed two pulses per read, i.e. 0x0022
  arriving at the ESP32's pin. The ESP32 was not sampling it: the `p` lead probe sets GPIO 19 to a plain input to
  test it and then calls SPI.begin() again, and on this ESP32 core a second begin() does not hand the pin back to the
  SPI hardware. Every earlier `p` had been followed by an upload (a reboot) before the next test, which hid it.
  Fix: SPI.end() before the begin(). Proven: regression PASS, then `p`, then regression PASS again. Lesson for the
  bench: when the chip's reply is on the wire but the host reads zero, suspect the host's pin setup before the leads.
- 4 Nov 2026 (02:00): the three-engine confirming run (41697384154, TT commit 2c401e2) built in 2h44m, gate-level test PASS, and **the viewer job passed for the first time** now the repo is public with Pages on: the layout is viewable at https://markstanners1-arch.github.io/ttihp-protocol-emulator/ . Precheck was still running at this check; expected to pass as the measurement run did.
- 4 Nov 2026 (01:30): **the backups had not reached GitHub since the isolation commit**: a 309 MB Copilot installer had
  been downloaded into the project folder, the backup's "add everything" swept it in, and GitHub refuses files over
  100 MB, so every push after that was rejected while the script's last line still read as success. Found while
  removing the bench photo (which, as a result, had never reached GitHub: it was folded out of the unpushed commits and
  is kept at D:\ outside the repo). Fix: installer dropped from the commit and moved to Downloads, `*.exe *.msi *.rar`
  gitignored, nine local commits folded into one and pushed. Lesson: read the whole backup output, not its last line.
- 4 Nov 2026 (morning): run 41697384154 precheck PASS, so the three-engine chip as it stands is a complete, submittable
  layout. Morning's bus talk (speed grades, the 400 pF capacitance limit, three- and four-wire variants, fire loops)
  turned into a "what else can it do" list; Mark's Elegoo kits cover most of it. **First new program: the 4x4 keypad
  scanner** `programs/keypad.asm` (16 words): one column pulled low at a time, open drain, so two keys on a row can never
  short two drivers; rows read with pull-ups; the 16-key map is pushed only when it changes, then a 20 ms pause for the
  bounce. `model/test_keypad.py` scans a model keypad (one key, a key bouncing for 5 ms each way, two keys on one row,
  all sixteen in turn, one column ever driven) PASS at the kit's and the ASIC's dividers; a planted short pause was
  caught (extra pushes on bounce). Sketch command `y` (engine B, names the keys, compiles); wiring sheet section 6
  (keypad on J4-14..17 columns and 27..30 rows with 10 k pull-ups, plus IR receiver and HC-SR04 rows for the next two
  programs). **Keypad PASS on the kit** (midday): idle map 0000, a scripted sequence (1, 5, 9, D, * with #, 4 with 6) read
  back exactly, twice, two at once including two on one row, one report per change, no bounce. The first "pass" had
  columns 3 and 4 crossed (tail pins 7 and 8 swapped at J4-16/17): the names looked plausible until checked against
  what was actually pressed. Lesson: test a keypad with a scripted sequence, never "press some keys". On the way: every key "pressed" = the row pull-ups not
  reaching J4-27..30 (the columns had been wired through the 10 ks); then rows 1 and 3 only, both ends of their
  resistors at the rail voltage (no current, so open), while the good rows showed a 0.5 V drop from the FPGA's internal
  pull-down. New sketch command `e` (live level of engine pins 15-19 for 30 s, a line on every change) found the lead
  fault at once. The kit's silkscreen marks the 3.3 V holes IO1, not a ball name.
- 4 Nov 2026 (afternoon): **NEC infrared remote decoder** `programs/ir_nec.asm` (29 words, engine B, tick 50 us: clkdiv 599
  at 12 MHz, 2499 at 50 MHz; in_base = jmp_pin = 1, no outputs). Every length is judged by a counting loop that polls the
  pin with `jmp pin` while X counts down, no stopwatch: leader burst at least 4.5 ms (else noise, back to idle), leader
  space over 3.3 ms = a data frame (shorter = the 2.25 ms repeat frame), bit space over 1.1 ms = a 1. Bits shift in LSB
  first and `push iffull` sends each 16: two words a frame (address pair, then command pair); a repeat frame pushes
  0xFFFF. A bit space stuck high for another 2.5 ms abandons the frame so a cut-short frame cannot garble the next one.
  The inverse check is left to the host (the sketch). `model/test_ir_nec.py` plays a model receiver (frames, repeats,
  stray pulses, 5 % fast and 5 % slow, a wrong inverse, extended NEC, frames cut at 9 and 20 bits) PASS at both dividers;
  a planted bit threshold (10 changed to 20) failed every frame, then removed. The IR test session's review caught two
  wrong comments (margins, and a loop loaded with N polls N+1 times); fixed. Sketch commands `m` (decoder: prints address
  and command, repeat count, flags a bad inverse) and `j` (raw low-pulse lengths). **Bench PASS, with a long road to it:**
  (1) three runs saw nothing because the module was not wired yet; pin 1 has a pull-up in the kit build, so "idle high"
  proved nothing and the sketch now says so. (2) The line then read stuck LOW 800 of 800: Mark had wired the Elegoo IR
  **emitter** (KY-005, a clear LED) instead of the receiver; the pads on the receiver are marked G R Y (ground, power, signal).
  (3) With the receiver in, a raw capture showed a steady train of 5 ms pulses every 36 ms: Mark's phone, confirmed later: opening its
  camera app does it (the infrared autofocus or depth sensor pulses at the receiver). Keep a phone with its camera open away from the receiver
  during captures; to check the emitter with a phone camera, hold it well to the side of the receiver. (4) A scripted window then read back correctly:
  1, 2, 3, 4, 5, 6, 7, 8, 9, 0, POWER, VOL+ held gave 12 frames in order (command bytes B7 B6 B5 C2 C1 C0 C7 C6 C5 C9
  B3 E0, address word 2916, the VOL+ hold 17 repeats at 108 ms), and an earlier 1, 2, 3, VOL+, POWER window gave the same
  codes. Mark's LG smart remote (thumb wheel) power key read address 04 command 08 with both inverses good. This remote (a Manhattan) has NEC timing but a
  16-bit address and command with no inverse rule, so the sketch flags BAD INVERSE on every key; that is the remote, not
  the decoder. Code table in `docs/bench_wiring.md` section 6 (PDF rebuilt), occupancy table section 7 (holes 2 and 8
  taken). There is no Elegoo remote (the kit has only the IR emitter board), so the remotes read were an LG smart remote and a Manhattan. Lessons: send a command letter twice
  and the second stops the first, so check the sketch is idle before a timed window; a pulled-up input reads high
  with nothing connected.
- 4 Nov 2026 (evening): **logic analyser set up and the IR decoder checked against it.** Binghe 8-channel 24 MHz USB analyser
  (a Saleae Logic clone, USB ID 0925:3881). Windows needed the WinUSB driver (Zadig, the copy that comes with PulseView); it
  then loads the sigrok fx2lafw firmware and shows as "Saleae Logic with 8 channels". **PulseView 0.4.2 crashes on Windows 11**
  (access violation in its auto-scan, hang or crash on capture, and its Python 3.4 cannot load one newer decoder): use the
  nightly installers instead, now in D:\Tools\PulseView and D:\Tools\sigrok-cli (sigrok-cli 0.8.0). The old 0.4.2 stays
  in C:\Program Files (x86)\sigrok and can be uninstalled. Capture from the command line, no window needed:
  `sigrok-cli --driver fx2lafw --config samplerate=24m --samples 2m --triggers D0=f -o file.sr` (CH1 = D0, CH8 = D7, the CLK
  lead unused), decode with `sigrok-cli -i file.sr -P ir_nec:ir=D0`. First capture, the Manhattan remote's button 1, CH1 on
  J4-8: sigrok's NEC decoder reads address 0x16 / 0x29 and command 0xB7 / 0x5C (flagging both inverse pairs, as the sketch
  did: 2916 and 5CB7), and the raw samples give leader burst 9.01 ms, leader space 4.53 ms, bit bursts 531-556 us, 0 spaces
  600 us, 1 spaces 1706-1733 us, so the decoder's 4.5 ms, 3.3 ms and 1.1 ms thresholds sit 0.5 ms or more from every real
  edge (the receiver module shortens bursts and lengthens spaces by about 20 and 40 us). The capture is saved as
  `docs/bench/ir_nec_manhattan_button1.sr` (open it in PulseView or sigrok-cli). Not done: a chip-side trace beside it
  (CH1 on J4-8 plus the ESP32's CS on CH2) and I2C/SPI captures.
- 4 Nov 2026 (night): **NEC infrared transmitter** `programs/ir_tx.asm` (31 words, engine A, partner of the decoder). The host pushes the
  same two words the decoder pushes (address | ~address << 8, command | ~command << 8, so extended 16-bit addresses and odd
  remotes go through); the engine sends the 9 ms / 4.5 ms leader, 32 bits LSB first and the closing burst, with the 38 kHz
  carrier made in software. Tick = a third of a carrier cycle (8.67 us: clkdiv 103 at 12 MHz, 433 at 50 MHz); a cycle is pin
  high, pin low, loop = 38.4 kHz at one third duty in a bit burst, 37.7 kHz averaged over the leader (its two nested loops add
  2 ticks per 30 cycles; the first version, 18 x 18, averaged 36.8 kHz, found by the model test and fixed). One space a frame
  (after bit 16, where the second word is fetched) is 44 us long. The repeat frame (2.25 ms space) is not generated: 31 of 32
  words are used, and receivers accept repeated full frames. `model/test_ir_tx.py` runs transmitter, a model receiver module
  (low while carrier was seen in the last 40 us) and `ir_nec.asm` together: LED idle and low, carrier within tolerance, leader 8.74 ms
  and space 4.49 ms, every bit within 8 % and each bit period within 2 %, an independent decoder in the test reads back the word, the
  line stays low after the closing burst, and engine B pushes the two words sent. PASS at 12 MHz (plain NEC, all zeros, all
  ones, the Manhattan's raw words) and at 50 MHz (two frames). Planted bug (the 1-space loop cut from 4 x 32 to 2 x 32 ticks):
  16 bits out of tolerance and engine B decoded 8400 / 8000 and similar garbage; removed. Sketch command `t` (A transmits to the
  emitter on engine pin 9, J4-19 / H14; B decodes the receiver; six frames compared word for word, and a failure says whether A never
  sent it or the receiver did not see it). **Bench PASS first time**: emitter signal to H14, G to GND, middle pin open, facing the
  receiver a few cm away: all six frames (address 00 command 45, LG power 04/08, 5A/3C, all ones, all zeros, the Manhattan's raw
  2916 5CB7) came back exactly. With the emitter unwired the same command failed as designed: A sent it, B got nothing.
  Wiring sheet: emitter rows, hole 19 taken (PDF rebuilt). Not yet done: the emitter pin on the logic analyser (CH2 on H14, CH1 on J4-8)
  to measure the real carrier and burst lengths.
- 4 Nov 2026 (night, later): **IR transmitter checked on the logic analyser.** CH1 on the receiver output (J4-8), CH2 on the emitter
  signal (H14), GND on J4-11, 24 MHz, trigger on the emitter's first edge; the capture is `docs/bench/ir_tx_loopback_00_45.sr`
  (address 00 command 45, the first frame of the `t` run). The receiver channel, an independent witness of what the emitter really
  sends, shows: leader low 8.76 ms, space 4.47 ms, 32 bit lows of 526-555 us, short spaces 564-592 us, long spaces 1681-1726 us,
  closing low 531 us, frame 67.5 ms, and the 32 bits read back as BA45FF00, exactly what was sent. Compared with the Manhattan
  remote's real frame (9.01 / 4.53 ms, lows 531-556 us, spaces 600 and 1706-1733 us) every figure is within 5 %. The emitter channel
  gives the carrier cycle (median 26.00 us = 38.46 kHz, the 3-tick design) but not the pulse width or a full burst train: the IR LED
  holds its own pin near its forward voltage (about 1.2 V), below the analyser's input threshold, so only the leading edge spikes
  above it, intermittently. To see that waveform use the Hantek scope on H14. Bench lessons: the analyser's CLK lead is not an
  input (it was clipped there for a while); sigrok-cli sometimes exits without writing its file when the output path is in the
  temp folder, so captures now go to D:\Tools\sigrok_captures first; and an unconnected analyser input floats high, so "all
  channels high" proves nothing.
- 4 Nov 2026 (late night): **the Pico 2 arrived and is a second host.** MicroPython v1.29.0 for the RP2350 (`RPI_PICO2-20260824-v1.29.0.uf2`,
  661,504 bytes, from micropython.org, kept in D:\Tools\pico2_micropython) copied onto the boot drive; it comes up on a COM port as
  "USB Serial Device", 150 MHz. `pico/chip_host.py` is the host module (SPI0 on its default pins, the same 16-bit command and
  one-burst program load as the ESP32 sketch), `pico/programs.py` the assembled programs (now generated by
  `python esp32/make_programs_h.py` beside programs.h), `pico/id_test.py` the first test. No pyserial or mpremote on the PC, so
  `pico/put.ps1` copies files over the serial raw REPL and `pico/run.ps1` runs a script and shows the output. Checked with nothing wired:
  the code runs and fails cleanly (a floating MISO reads 0x0000). Wiring in sheet section 8 (CS GP17, MOSI GP19, MISO GP16, SCK GP18,
  IRQ GP20, GND pin 23; one host at a time). Next: wire it, ID register 0x0022, then port the IR decoder and the keypad.
- 4 Nov 2026 (night, Pico on the bench): **the Pico 2 drives the chip.** Five SPI/IRQ leads and the ground moved from the ESP32 to the
  Pico (sheet section 8). `pico/id_test.py`: ID register 0x0022 five times, spec 2, two engines, PASS. Ported from the ESP32 sketch
  and run from the Pico, all against the same kit build: `pico/ir_loopback.py` (engine A transmits through the emitter, engine B
  decodes from the receiver) **PASS 6 of 6 frames exactly**, the first run; `pico/ir_decode.py` (the sketch's `m`) with the Manhattan
  remote pressing 1, 2, 3, POWER read B7, B6, B5, B3 with a tap's two or three repeats each: the same codes the ESP32 read; `pico/keypad.py`
  (the sketch's `y`) with the sequence 1, 5, 9, D, * with #, 4 with 6 read back line by line, each key one report on press and one of
  0000 on release, pairs as both bits, except that **D appeared twice** the first time where the sequence had it once. Mark did not knowingly press it twice; a rerun of
  the same sequence read D once and everything else identically (PASS). Not bounce as such: the program waits 20 ms after every change,
  so a double report needs the contact to open and close again for longer than that, e.g. a slow press on a tired membrane key. The chip needs no change to
  switch hosts: only the five host-port lines move. Scripts run with `pico/run.ps1 -Script <name>.py -Seconds n`.
