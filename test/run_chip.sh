#!/usr/bin/env bash
# End-to-end chip test. Optional: CHIP_SRC_OVERRIDE="file.v=replacement.v" to swap one source (planted bugs).
cd "$(dirname "$0")/.."
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
python test/gen_chip_test.py >/dev/null
SRCS="src/chip.v src/host_spi.v src/engine.v src/prog_mem.v src/glitch_filter.v"
if [ -n "$CHIP_SRC_OVERRIDE" ]; then SRCS="${SRCS/${CHIP_SRC_OVERRIDE%%=*}/${CHIP_SRC_OVERRIDE#*=}}"; fi
iverilog -g2012 -o test/build/tb_chip.vvp $SRCS test/tb_chip.v && (cd test/build && vvp -n tb_chip.vvp +late=${LATE:-0} | grep -vE "finish called")
