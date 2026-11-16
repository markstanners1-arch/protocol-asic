#!/bin/bash
# Colorlight i9 v7.2 (LFE5U-45F-6BG381): build a design and load it to the FPGA's SRAM through the breakout's USB-C DAPLink.
#   bash fpga/i9/build.sh [blink|blink_fast]    blink.v / blink_fast.v, built and loaded
#   bash fpga/i9/build.sh chip [load]           the Tiny Tapeout chip (chip_i9.v + chip_i9.lpf) at 40 MHz:
#                                               build/chip_i9.bit; loaded only with "load"
#     TT_REF=<commit>  the Tiny Tapeout repository commit whose src/ is built (default 856c569, as taped out);
#                      SRC=repo builds this repository's src/ instead
#     SEED=<n>         nextpnr placement seed (default 5: 40.29 MHz; 2 of 9 seeds tried on 16 Nov closed 40 MHz)
# SRAM only (no -f): the design is gone at power-off and the flash keeps the factory image.
# Plug the board straight into a PC socket.
set -e
cd "$(dirname "$0")"
T=/d/Tools/oss-cad-suite
export PATH="$T/bin:$T/lib:$PATH"
mkdir -p build
LOADER="openFPGALoader -c cmsisdap --vid 0x0d28 --pid 0x0204"

pack() {   # pack <name>
    rm -f "build/$1.bit"
    ecppack "build/$1.config" "build/$1.bit" || true   # the Windows ecppack exits 127 after writing a good file
    [ -s "build/$1.bit" ] || ecppack "build/$1.config" "build/$1.bit" || true
    [ -s "build/$1.bit" ] || { echo "ecppack wrote no bitstream"; exit 1; }
}

if [ "$1" != chip ]; then
    TOP=${1:-blink}
    yosys -q -p "synth_ecp5 -top $TOP -json build/$TOP.json" "$TOP.v"
    nextpnr-ecp5 -q --45k --package CABGA381 --speed 6 --json "build/$TOP.json" --lpf "$TOP.lpf" --textcfg "build/$TOP.config" \
        --log "build/$TOP.pnr.log"
    pack "$TOP"
    grep -E "Max frequency|TRELLIS_(COMB|FF|IO):" "build/$TOP.pnr.log" | tail -4 || true
    $LOADER "build/$TOP.bit"
    exit 0
fi

NAME=chip_i9
FILES="chip.v cluster.v host_spi.v engine.v serialiser.v receiver.v crc32.v prog_mem.v fifo_mem.v glitch_filter.v"
if [ "$SRC" = repo ]; then
    S=../../src; echo "== $NAME: this repository's src/ ($(git rev-parse --short HEAD))"
else
    REF=${TT_REF:-856c569}; S=build/tt_src
    mkdir -p $S
    for f in $FILES; do git -C /d/ProtocolASIC_TT show "$REF:src/$f" > "$S/$f"; done
    echo "== $NAME: Tiny Tapeout src/ at $(git -C /d/ProtocolASIC_TT rev-parse --short "$REF")"
fi
SRCS=""; for f in $FILES; do SRCS="$SRCS $S/$f"; done

# Program stores (32 x 16) marked block RAM: left alone, yosys puts them in LUT RAM. The 1024-word buffer maps to one
# DP16KD (1024 x 18) by itself.
yosys -l "build/$NAME.yosys.log" -q -p "read_verilog $SRCS chip_i9.v; hierarchy -top chip_i9; proc; opt_clean; \
    setattr -set ram_style \"block\" prog_mem/mem; synth_ecp5 -top chip_i9 -json build/$NAME.json; stat"
nextpnr-ecp5 -q --45k --package CABGA381 --speed 6 --json "build/$NAME.json" --lpf chip_i9.lpf \
    --textcfg "build/$NAME.config" --seed "${SEED:-5}" --log "build/$NAME.pnr.log" --timing-allow-fail
pack "$NAME"
echo "built build/$NAME.bit"
grep -E "Total LUT4s|TRELLIS_(COMB|FF|IO):|DP16KD:" "build/$NAME.pnr.log" || true
grep -E "Max frequency for clock" "build/$NAME.pnr.log" | tail -1 || true
[ "$2" = load ] && $LOADER "build/$NAME.bit"
exit 0
