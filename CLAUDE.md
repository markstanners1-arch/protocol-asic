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

## State at handover (3 Nov 2026, 00:50)
Chip is **ISA v0.2** (`side_dir`, MISC bit 13: side-set can write pin directions, for open-drain SCL). Proven: model = Verilog
on 520K random clocks, whole-chip test, MachXO3L kit + ESP32 hardware test 0 problems. **First Tiny Tapeout layout (v0.1):
33.5 % of 6x4, 50 MHz met at all corners, precheck and gate-level test pass**; the viewer job always fails on a private repo.
The v0.2 layout run was still building (run 41543287970): read it with ONE `gh run view`, never `gh run watch` (it tripped
GitHub's rate limit for 40 min). **I2C proven on real wires** against the ESP32 (no stretch) and an UNO R3 slave with clock
stretching and repeated START (`esp32/rerun.ps1 -Cmd i` / `-Cmd n`; not both boards at once, both are 0x50). Bench wiring
now: J4-10/13 = I2C SCL/SDA (GPIO 22/21, UNO A5/A4, 5.1 k to 3.3 V); J4-14..17 = SPI to a 74HC595 (SCK, MOSI, MISO from QH',
latch), LEDs still dark: see the README's last entry. Cyclone IV: Quartus project ready (`fpga/cyclone4`), pins TODO.
Next: finish the 595 SPI bench test; Cyclone IV pins and the same ESP32 test at 50 MHz; SPI/DHT11/IR as further
protocols; a MicroPython host for the RP2040 demo board; a real I2C part (24C EEPROM or DS3231) when one turns up.
