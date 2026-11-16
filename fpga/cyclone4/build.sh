#!/usr/bin/env bash
# Build the whole chip for the Cyclone IV E board with Quartus Prime Lite (second-opinion toolchain),
# and with "load" put it in the FPGA's volatile SRAM over the USB Blaster (JTAG; lost at power-off, never the flash).
#   bash fpga/cyclone4/build.sh            three engines at 50 MHz, no serialiser: build/chip_c4.sof (ID 0x0023)
#   bash fpga/cyclone4/build.sh ser        engine 0 with the serialiser and 64-word TX FIFO, chip clock 40 MHz from the
#                                          PLL, SER_NENG engines (default 2): build/chip_c4_ser<N>.sof
#   ... load                               then load that file into the FPGA (SRAM only)
# Prints LEs, memory bits and Fmax.
set -e
cd "$(dirname "$0")"
Q=/d/Tools/altera_lite/quartus/bin64
SER=0; LOAD=0
for a in "$@"; do
    case "$a" in
        ser)  SER=1 ;;
        load) LOAD=1 ;;
        *)    echo "unknown option $a (ser, load)"; exit 1 ;;
    esac
done
MAP_ARGS=""; OUT=chip_c4
if [ $SER = 1 ]; then
    N=${SER_NENG:-2}
    MAP_ARGS="--verilog_macro=SER_BUILD=1 --verilog_macro=SER_NENG=$N"
    OUT=chip_c4_ser$N
fi
mkdir -p build
$Q/quartus_map chip_c4 $MAP_ARGS > build/map.out 2>&1 || { tail -20 build/map.out; exit 1; }
$Q/quartus_fit chip_c4 > build/fit.out 2>&1 || { tail -20 build/fit.out; exit 1; }
$Q/quartus_sta chip_c4 > build/sta.out 2>&1 || { tail -20 build/sta.out; exit 1; }
$Q/quartus_asm chip_c4 > build/asm.out 2>&1 || { tail -20 build/asm.out; exit 1; }
[ $OUT != chip_c4 ] && cp build/chip_c4.sof build/$OUT.sof
echo "built build/$OUT.sof"
grep -E "Total logic elements|Total registers|Total memory bits|Total PLLs" build/chip_c4.fit.summary
grep -A6 "; Slow 1200mV 85C Model Fmax Summary" build/chip_c4.sta.rpt | grep MHz
grep -E "Timing requirements not met|Critical Warning" build/sta.out | head -3 || true
[ $LOAD = 1 ] && $Q/quartus_pgm -m jtag -o "p;build/$OUT.sof"
exit 0
