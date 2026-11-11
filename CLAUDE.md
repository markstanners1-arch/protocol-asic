# D:\ProtocolASIC: protocol emulator ASIC (Jane Street / Tiny Tapeout competition)

Mark Stanners + Claude, started 2 Nov 2026. **Submit by 18 Jan 2027**. Read `README.md` first:
what the chip is, its layout, verification and bench results. Specs: `docs/core_design.md`, `docs/isa.md`
(exact engine rules), `docs/host_port.md`, `docs/input_filter.md`.

## Rules
- Bench rule: a lead or key fault is checked by continuity to the labelled pads, or with `programs/read_pins.asm`,
  before blaming the design; a bench pass needs a scripted sequence read back line by line.
- After changes, back up: `pwsh D:\NINA\backup_scripts.ps1 "what changed"` (pushes the GitHub repo
  markstanners1-arch/protocol-asic and copies to G:\My Drive\Astro scripts\ProtocolASIC).
- Every design change is proven three ways: the Python model (`model/`, the reference), the side-by-side
  random test (`python model/cosim.py 1000 400 <seed>`, plus `USE_SRAM=1`), and the whole-chip test
  (`bash test/run_chip.sh`, also `LATE=1`). Plant a bug to check any new test catches it.
- Big method changes (memory type, architecture): ask Mark first.
- **Never write the MachXO3L kit's one-time NVCM.** Load SRAM only: `openFPGALoader -b machXO3SK file.bit` (no -f).
  The Mojo loads to FPGA RAM only (`python fpga/mojo/load.py <port> <bin>`, no `--flash`); the Cyclone to SRAM only over
  JTAG (`quartus_pgm -m jtag -o "p;<file>.sof"`).
- 3.3 V logic only on the chip's pins.

## Tools and bench (see README for details)
- OSS CAD Suite at `D:\Tools\oss-cad-suite` (iverilog, verilator via `verilator_bin` + VERILATOR_ROOT, yosys,
  nextpnr, openFPGALoader). Quartus Prime Lite 25.1 at `D:\Tools\altera_lite` (Cyclone IV E; USB Blaster driver in).
- **MachXO3L Starter Kit** (main bench board): `bash fpga/machxo3/build.sh` then load as above. The free MachXO tools
  break LUT RAM *and* block RAM on hardware, so the script uses `-nolutram -nobram` (84 % full, ~28 MHz, kit runs 12 MHz).
  The kit's USB serial isn't fitted; header J4 is soldered.
- **ESP32** (CH340; the port moves when the USB plugs change, the scripts find it automatically; EN capacitor fitted so uploads are hands-free): `esp32\upload_and_watch.ps1 -Sketch chip_test`,
  `esp32\rerun.ps1`. Wiring J4 -> ESP32: K12 CS->5, M14 MOSI->23, L14 MISO->19, M15 SCK->18, GND, N14 (engine pin 0)->16,
  K13 IRQ->4, G15 (engine pin 15)<-17. Programs for the ESP32 come from `python esp32/make_programs_h.py`.
- **Go Board** (iCE40 HX1K): too small for an engine; used for UART, host-port and bounce tests. Its 7-segment display is
  dead. Moving it to another USB socket needs Zadig (WinUSB on interface 0) again.
- **Cyclone IV EP4CE6 board** (black EP4CE6E22C8N core board, USB Blaster on its JTAG header): `bash fpga/cyclone4/build.sh`
  (three engines at 50 MHz, ID 0x0023) or `build.sh ser` (40 MHz from the PLL, engine 0 with the serialiser and receiver,
  two engines, ID 0x0022). Pins in `fpga/cyclone4/chip_c4.qsf`.
- **Mojo v3** (Spartan-6 LX9, Xilinx ISE 14.7): `fpga/mojo/` build script, loaded with `fpga/mojo/load.py`.
- **Raspberry Pi Pico host** (MicroPython): `pwsh pico/run.ps1 -Script <file>.py -Seconds <n> -Pre "CHIP_HZ=40_000_000"`;
  host library `pico/chip_host.py`, programs from `pico/programs.py`.
- **Tiny Tapeout repo**: `D:\ProtocolASIC_TT` = github.com/markstanners1-arch/ttihp-protocol-emulator (public; Pages
  viewer at markstanners1-arch.github.io/ttihp-protocol-emulator; IHP CMOS5L template, 6x4 tiles, 40 MHz, top
  `tt_um_gosforth_protocol_emu`). Its `src/` is a copy of this repo's `src/` plus the wrapper `project.v`, `config.json`,
  `pnr.sdc` and the SRAM model; re-copy after changes. A gds run starts on every push (~2.5 h with precheck): read it
  with ONE `gh run view`, never watch or poll.

## State (11 Nov 2026)
- **8x4 tiles** (Jane Street, 9 Nov: confirmed and final).
- **Tiny Tapeout main = 856c569** (11 Nov): 8x4 tiles, engine 0's buffer at 1024 words (`TXDEPTH0`, IHP
  `RM_IHPSG13_1P_1024x16_c2_bm_bist`, macro path `...e.tx_mem.txmem.ram1k.sram`), 512 + 512 in full duplex, registers
  0x38 SERLEVEL and 0x39 RXWORDS; the src as laid out on branch `buffer-1k` (26,827 cells, 41.1 %, setup +7.15 ns,
  hold +0.135 ns, every job passing). FPGA serialiser builds keep 64 words (pass `TXDEPTH0=64`). Proven: model
  (`model/test_buffer1024.py`), cosim at both depths (`TXDEPTH0=64`; long runs `RX_FOCUS=1 python model/cosim.py 24
  40000 <seed>`), chip test, 4 planted bugs; the 1024-word buffer itself not yet on the bench.
- Ethernet into a PC adapter: 1000 of 1000 frames with 100 R per line and 220 pF across the pair.
- ARP and ping answered on the model (`pico/netstack.py`, `model/test_netstack.py`); the bench needs a receive front end.
- **The chip before it on Tiny Tapeout main** (a994a97, 6x4 tiles): four engines without CRC units, IHP SRAM macros for
  the program stores and engine 0's 64-word TX FIFO, 40 MHz, ID 0x0024, with receive and full duplex on engine 0
  (Manchester receiver, keyed mode in SERCFG [8:7], 16/48-word rings, RXDATA 0x37, hardware preamble; receive pin latch
  `sg13cmos5l_dlhq_1` in the wrapper, `test/rtl_cells.v` for the RTL test). Layout clean: 25,457 cells, 46.5 %
  utilisation, setup +7.08 ns, hold +0.151 ns at the fast corner (hold-fix target 0.15 ns), DRC/LVS/antenna 0,
  gate-level test and precheck pass. Proven by model, cosim, chip test, planted bugs and on the Mojo (`pico/fdx_loop.py`).
- Host port and ISA v0.4 (docs/isa.md). Bench wiring in `docs/bench_wiring.md`. A Hantek DSO5102P oscilloscope is on
  the bench for scope captures.
