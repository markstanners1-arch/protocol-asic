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
- **Tiny Tapeout repo**: `D:\ProtocolASIC_TT` = github.com/markstanners1-arch/ttihp-protocol-emulator (public since 3 Nov, as is protocol-asic; Pages on, viewer at markstanners1-arch.github.io/ttihp-protocol-emulator; IHP
  CMOS5L template, 6x4 tiles, 50 MHz, top `tt_um_gosforth_protocol_emu`). Its `src/` is a copy of this repo's `src/`;
  re-copy after changes. The cocotb test passes on GitHub; the first two layout (gds) runs were still building at
  ~21:45 on 2 Nov: check `gh run list -R markstanners1-arch/ttihp-protocol-emulator`.

## State at handover (3 Nov 2026, night)
Chip is **three engines** (`protocol_chip` default `NENG = 3`; decided 3 Nov: four at 61 % of the core failed detailed
placement twice, three at 49.5 % laid out clean: timing met at all corners, DRC/LVS/antenna 0, gate-level test and
precheck pass; stats in `docs/layout/metrics_3nov_v02_3eng.csv`). Host port v0.2 (16-bit command `[15] read, [14:12]
engine, [5:0] register`, ID register 0x2A reads `[7:4]` spec 2 / `[3:0]` engines, lowest engine wins a pin). ISA v0.2.
I2C master is 19 words. Proven at three: cosim 400K clocks both memories, whole-chip test NENG=3/2, LATE=0/1.
TT repo commit after f087b2d: wrapper uses the chip default, metadata "three"; a gds run starts on push (~2.5 h + 40 min
precheck): read with ONE `gh run view`, never watch. **Bench (rebuilt 3 Nov, `docs/bench_wiring.md` / `.pdf`):** MachXO3L
kit with two engines, ESP32 host on COM12 (scripts find the port): regression PASS (ID 0x0022), I2C PASS with the
ESP32 and the UNO slaves, SPI PASS to a 74HC595 (red/yellow LEDs only at 3.3 V). Sketch bench helpers: p lead probe,
q IRQ hold, l scope loop, b I2C wire check, k SCL hold, w LED walk, a I2C address scan. Cyclone IV board (black
EP4CE6E22C8N core board) pinned (`fpga/cyclone4/chip_c4.qsf`, right-hand header 38-72, clock pin 24), builds three
engines at 98 % / 51.6 MHz with area optimisation; **needs the USB Blaster, due 5-6 Nov** (eBay, Leicester).
Next: Blaster -> Cyclone at 50 MHz with three engines (ID 0x0023), same ESP32 tests; the "what is this chip?" demo
(address scan done; SPI JEDEC ID, pin levels and periods next); trade protocols (DALI, DMX512, Modbus RTU, Wiegand);
MicroPython host for the RP2040 demo board. Mark's Hantek DSO5102P is on the bench if a scope capture is wanted.
