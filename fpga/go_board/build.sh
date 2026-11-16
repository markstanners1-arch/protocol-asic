#!/usr/bin/env bash
# Build the Go Board hello test:  ./build.sh        (bitstream to build/hello.bin)
#                     and flash:  ./build.sh prog   (needs the board plugged in and the WinUSB driver on its interface 0)
set -e
cd "$(dirname "$0")"
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
mkdir -p build
yosys -q -l build/yosys.log -p "read_verilog ../../src/uart_tx.v hello_top.v; synth_ice40 -top hello_top -json build/hello.json"
nextpnr-ice40 --hx1k --package vq100 --pcf go_board.pcf --json build/hello.json --asc build/hello.asc --freq 25 -q -l build/pnr.log
icepack build/hello.asc build/hello.bin
grep -E "ICESTORM_LC:|Max frequency" build/pnr.log
[ "$1" = "prog" ] && iceprog build/hello.bin
exit 0
