#!/bin/bash
# RTL test of the i9 wrapper: bash fpga/i9/sim.sh. Uses the sources build.sh extracted (build/tt_src, the taped-out
# commit), so run bash fpga/i9/build.sh chip first; SRC=repo tests this repository's src/ instead.
set -e
cd "$(dirname "$0")"
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
S=build/tt_src; [ "$SRC" = repo ] && S=../../src
[ -f $S/chip.v ] || { echo "no $S: run build.sh chip first"; exit 1; }
iverilog -g2012 -o build/tb_chip_i9.vvp $S/chip.v $S/cluster.v $S/host_spi.v $S/engine.v $S/serialiser.v \
    $S/receiver.v $S/crc32.v $S/prog_mem.v $S/fifo_mem.v $S/glitch_filter.v chip_i9.v tb_chip_i9.v
(cd build && vvp -n tb_chip_i9.vvp | grep -vE "finish called")
