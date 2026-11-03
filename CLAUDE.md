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
- **ESP32** (CH340; the port moves when the USB plugs change, the scripts find it automatically; EN capacitor fitted so uploads are hands-free): `esp32\upload_and_watch.ps1 -Sketch chip_test`,
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

## State at handover (3 Nov 2026, afternoon)
Chip is **four engines** (`protocol_chip #(NENG)`, 4 on the ASIC; the FPGA tops pass 2 because neither board fits four),
**host port v0.2**: a 16-bit command `[15] read, [14:12] engine, [5:0] register`, ID register 0x2A (`[3:0]` engines,
`[7:4]` spec 2), lowest engine wins a pin, IRQ from any engine. ISA v0.2 unchanged. I2C master is 19 words (one `xfer`
routine: nine SDA levels out, nine seen back as byte << 1 | ACK; a sent byte read back differently = arbitration lost).
Proven: model I2C test, cosim 400K clocks both memories, whole-chip test NENG=4 and NENG=2, LATE=0/1, four planted bugs
caught; ESP32 sketch compiles (two-byte command, ID check) but is **not yet run on hardware: Mark cleared the bench and is
rewiring from scratch; the Cyclone IV board arrived 3 Nov**. MachXO3 build 30.9 MHz, Cyclone 71 % LEs, both two engines.
TT repo commit 2d2a76c: cocotb test PASS; **gds run 41642156659 started 13:11, read it after ~15:30 with ONE `gh run view`**
(never `gh run watch`). The v0.2 two-engine layout before it: 33.9 %, timing met, DRC/LVS clean.
Next: read the four-engine layout (utilisation, timing); rebuild the bench (one wiring sheet: J4 -> ESP32 as in Tools above,
then I2C/SPI pins as needed) and rerun `esp32/rerun.ps1` (ID should read 0x0022 on an FPGA); Cyclone IV pins in
`fpga/cyclone4/chip_c4.qsf` and the same test at 50 MHz; then trade protocols (DALI, DMX512, Modbus RTU, Wiegand) and
the 74HC595 SPI bench test.
