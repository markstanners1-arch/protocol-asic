#!/usr/bin/env bash
# Build the whole chip for the MachXO3L Starter Kit and (with "load") put it in the FPGA's volatile SRAM.
#
#   bash fpga/machxo3/build.sh [load]        default build -> build/chip.bit
#       two engines (ID 0x0022) without the serialiser and the CRC units, 4-word TX FIFOs: the v0.2 engines.
#       5 Nov 2026: 5,953 of 6,864 LUTs (86 %), 2,087 flip-flops, fmax 28.74 MHz (kit clock 12 MHz).
#   bash fpga/machxo3/build.sh ser [load]    serialiser build -> build/chip_ser.bit
#       one engine (ID 0x0021) with the serialiser, the CRC unit and the 64-word TX FIFO (ISA v0.3, docs/isa.md).
#       5 Nov 2026: 4,785 of 6,864 LUTs (69 %), 2,328 flip-flops, fmax 29.63 MHz.
#   Two engines with the serialiser do not fit: 7,688 LUTs with the 64-word FIFO, 6,937 with a 16-word one.
#   KIT="NAME=value ..." sets the wrapper's parameters (NENG, SER0, CRC, TXDEPTH0) by hand, on top of the build chosen.
#
# NOTE -nolutram -nobram: on 2 Nov 2026 the free MachXO tools' distributed-RAM (LUT RAM) mapping broke the chip on real
# hardware (settings read back as 0, engines never started), and later their block-RAM (DP8KC) mapping of the
# program memories left the engines dead; the same design with neither passed on hardware and in gate-level sim.
# Never write the kit's one-time NVCM: openFPGALoader without -f loads SRAM only.
set -e
cd "$(dirname "$0")"
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
mkdir -p build
NAME=chip; P=""
if [ "$1" = "ser" ]; then NAME=chip_ser; P="NENG=1 SER0=1 CRC=1 TXDEPTH0=64"; shift; fi
S="../../src/chip.v ../../src/cluster.v ../../src/host_spi.v ../../src/engine.v ../../src/serialiser.v ../../src/crc32.v ../../src/prog_mem.v ../../src/fifo_mem.v ../../src/glitch_filter.v chip_mxo3.v"
CHP=""; for kv in $P $KIT; do CHP="$CHP chparam -set ${kv%%=*} ${kv#*=} chip_mxo3;"; done
yosys -q -p "read_verilog $S; $CHP synth_lattice -family xo3 -nolutram -nobram -top chip_mxo3 -json build/$NAME.json"
nextpnr-machxo2 --device LCMXO3L-6900C-5BG256C --json build/$NAME.json --lpf chip_mxo3.lpf --textcfg build/$NAME.config --freq 12 -q -l build/${NAME}_pnr.log
ecppack build/$NAME.config --bit build/$NAME.bit
grep -E "TRELLIS_COMB:|TRELLIS_FF:|Max frequency" build/${NAME}_pnr.log | tail -3
echo "built build/$NAME.bit"
[ "$1" = "load" ] && openFPGALoader -b machXO3SK build/$NAME.bit
exit 0
