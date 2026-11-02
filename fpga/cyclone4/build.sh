#!/usr/bin/env bash
# Build the whole chip for the Cyclone IV E board with Quartus Prime Lite (second-opinion toolchain),
# and with "load" put it in the FPGA's volatile SRAM over the USB Blaster (JTAG; lost at power-off, never the flash).
#   bash fpga/cyclone4/build.sh        synthesis, fit, timing, bitstream; prints LEs, M9Ks and Fmax
#   bash fpga/cyclone4/build.sh load   ...then load it into the FPGA
set -e
cd "$(dirname "$0")"
Q=/d/Tools/altera_lite/quartus/bin64
mkdir -p build
$Q/quartus_map chip_c4 > build/map.out 2>&1 || { tail -20 build/map.out; exit 1; }
$Q/quartus_fit chip_c4 > build/fit.out 2>&1 || { tail -20 build/fit.out; exit 1; }
$Q/quartus_sta chip_c4 > build/sta.out 2>&1 || { tail -20 build/sta.out; exit 1; }
$Q/quartus_asm chip_c4 > build/asm.out 2>&1 || { tail -20 build/asm.out; exit 1; }
grep -E "Total logic elements|Total registers|Total memory bits|Total RAM Blocks|Embedded Multiplier" build/chip_c4.fit.summary
grep -A4 "; Slow 1200mV 85C Model Fmax Summary" build/chip_c4.sta.rpt | grep MHz
grep -E "Timing requirements not met|Critical Warning" build/sta.out | head -3 || true
[ "$1" = "load" ] && $Q/quartus_pgm -m jtag -o "p;build/chip_c4.sof"
exit 0
