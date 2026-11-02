#!/usr/bin/env bash
# Build the whole chip for the MachXO3L Starter Kit and (with "load") put it in the FPGA's volatile SRAM.
# NOTE -nolutram: on 2 Nov 2026 the free MachXO tools' distributed-RAM (LUT RAM) mapping broke the chip on real
# hardware (settings read back as 0, engines never started), while the same design without LUT RAM passed.
# Never write the kit's one-time NVCM: openFPGALoader without -f loads SRAM only.
set -e
cd "$(dirname "$0")"
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
mkdir -p build
S="../../src/chip.v ../../src/host_spi.v ../../src/engine.v ../../src/prog_mem.v ../../src/glitch_filter.v chip_mxo3.v"
yosys -q -p "read_verilog $S; synth_lattice -family xo3 -nolutram -top chip_mxo3 -json build/chip.json"
nextpnr-machxo2 --device LCMXO3L-6900C-5BG256C --json build/chip.json --lpf chip_mxo3.lpf --textcfg build/chip.config --freq 12 -q -l build/chip_pnr.log
ecppack build/chip.config --bit build/chip.bit
grep -E "TRELLIS_COMB:|TRELLIS_RAMW:|Max frequency" build/chip_pnr.log | tail -3
[ "$1" = "load" ] && openFPGALoader -b machXO3SK build/chip.bit
exit 0
