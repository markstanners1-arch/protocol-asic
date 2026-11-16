#!/bin/bash
# Colorlight i9 v7.2 (LFE5U-45F-6BG381): build a design and load it to the FPGA's SRAM through the breakout's USB-C DAPLink.
#   bash fpga/i9/build.sh [blink|blink_fast]    blink.v / blink_fast.v, built and loaded
# SRAM only (no -f): the design is gone at power-off and the flash keeps the factory image.
# Plug the board straight into a PC socket.
set -e
cd "$(dirname "$0")"
T=/d/Tools/oss-cad-suite
export PATH="$T/bin:$T/lib:$PATH"
mkdir -p build
TOP=${1:-blink}
yosys -q -p "synth_ecp5 -top $TOP -json build/$TOP.json" "$TOP.v"
nextpnr-ecp5 -q --45k --package CABGA381 --speed 6 --json "build/$TOP.json" --lpf "$TOP.lpf" --textcfg "build/$TOP.config" \
    --log "build/$TOP.pnr.log"
rm -f "build/$TOP.bit"
ecppack "build/$TOP.config" "build/$TOP.bit" || true   # the Windows ecppack exits 127 after writing a good file
[ -s "build/$TOP.bit" ] || ecppack "build/$TOP.config" "build/$TOP.bit" || true
[ -s "build/$TOP.bit" ] || { echo "ecppack wrote no bitstream"; exit 1; }
grep -E "Max frequency|TRELLIS_(COMB|FF|IO):" "build/$TOP.pnr.log" | tail -4 || true
openFPGALoader -c cmsisdap --vid 0x0d28 --pid 0x0204 "build/$TOP.bit"
