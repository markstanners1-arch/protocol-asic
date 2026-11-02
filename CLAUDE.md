# D:\ProtocolASIC: protocol emulator ASIC (Jane Street / Tiny Tapeout competition)

Mark Stanners + Claude, started 2 Nov 2026. **Submit by 18 Jan 2027** (aim 11 Jan). Read `README.md` first:
the roadmap and a dated progress log of everything done and found. Specs: `docs/core_design.md`, `docs/isa.md`
(exact engine rules), `docs/host_port.md`, `docs/input_filter.md`, `docs/memory_options.md`.

## Mark
- (personal note removed)



- Check leads by continuity to the labelled pads, or with
  `programs/read_pins.asm`, before blaming the design.

## Rules
- After changes, back up: `pwsh D:\NINA\backup_scripts.ps1 "what changed"` (pushes the private GitHub repo
  markstanners1-arch/protocol-asic and copies to G:\My Drive\Astro scripts\ProtocolASIC).
- Every design change is proven three ways: the Python model (`model/`, the reference), the side-by-side
  random test (`python model/cosim.py 1000 400 <seed>`, plus `USE_SRAM=1`), and the whole-chip test
  (`bash test/run_chip.sh`, also `LATE=1`). Plant a bug to check any new test catches it.
- Big method changes (memory type, architecture): ask Mark first.
- **Never write the MachXO3L kit's one-time NVCM.** Load SRAM only: `openFPGALoader -b machXO3SK file.bit` (no -f).

## Tools and bench (see README for details)
- OSS CAD Suite at `D:\Tools\oss-cad-suite` (iverilog, verilator via `verilator_bin` + VERILATOR_ROOT, yosys,
  nextpnr, openFPGALoader). Quartus Prime Lite 25.1 at `D:\Tools\altera_lite` (Cyclone IV E; USB Blaster driver in).
- **MachXO3L Starter Kit** (main bench board): `bash fpga/machxo3/build.sh` then load as above. The free MachXO tools
  break LUT RAM *and* block RAM on hardware, so the script uses `-nolutram -nobram` (84 % full, ~28 MHz, kit runs 12 MHz).
  The kit's USB serial isn't fitted; header J4 is soldered.
- **ESP32** (CH340, COM7, EN capacitor fitted so uploads are hands-free): `esp32\upload_and_watch.ps1 -Sketch chip_test`,
  `esp32\rerun.ps1`. Wiring J4 -> ESP32: K12 CS->5, M14 MOSI->23, L14 MISO->19, M15 SCK->18, GND, N14 (engine pin 0)->16,
  K13 IRQ->4, G15 (engine pin 15)<-17. Programs for the ESP32 come from `python esp32/make_programs_h.py`.
- **Go Board** (iCE40 HX1K): too small for an engine; used for UART, host-port and bounce tests. Its 7-segment display is
  dead. Moving it to another USB socket needs Zadig (WinUSB on interface 0) again.
- **Cyclone IV EP4CE6 board**: arriving 3 Nov 2026. Plan: build the same chip in Quartus as a second-opinion
  toolchain, run the same ESP32 test.
- **Tiny Tapeout repo**: `D:\ProtocolASIC_TT` = github.com/markstanners1-arch/ttihp-protocol-emulator (private, IHP
  CMOS5L template, 6x4 tiles, 50 MHz, top `tt_um_gosforth_protocol_emu`). Its `src/` is a copy of this repo's `src/`;
  re-copy after changes. The cocotb test passes on GitHub; the first two layout (gds) runs were still building at
  ~21:45 on 2 Nov: check `gh run list -R markstanners1-arch/ttihp-protocol-emulator`.

## State at handover (2 Nov 2026, ~21:45)
Whole chip (two engines, SPI host port, glitch filter) passes every hardware test on the MachXO3L + ESP32.
Next: layout results; Cyclone IV second opinion; I2C/SPI-master programs with model partners; SRAM decision at layout.
