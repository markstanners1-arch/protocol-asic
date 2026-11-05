#!/usr/bin/env bash
# End-to-end chip test. Optional: CHIP_SRC_OVERRIDE="file.v=replacement.v" to swap one source (planted bugs);
# NENG=2 to test the two-engine build the kit uses (default 3, the ASIC); LATE=1 to sample MISO late;
# SER0=0 CRC=0 TXDEPTH0=4 for the kit's default build (no serialiser, no CRC units, 4-word TX FIFO).
cd "$(dirname "$0")/.."
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
python test/gen_chip_test.py >/dev/null
SRCS="src/chip.v src/cluster.v src/host_spi.v src/engine.v src/serialiser.v src/crc32.v src/prog_mem.v src/glitch_filter.v"
if [ -n "$CHIP_SRC_OVERRIDE" ]; then SRCS="${SRCS/${CHIP_SRC_OVERRIDE%%=*}/${CHIP_SRC_OVERRIDE#*=}}"; fi
iverilog -g2012 -P tb_chip.NENG=${NENG:-3} -P tb_chip.SER0=${SER0:-1} -P tb_chip.CRC=${CRC:-1} -P tb_chip.TXDEPTH0=${TXDEPTH0:-64} -o test/build/tb_chip.vvp $SRCS test/tb_chip.v && (cd test/build && vvp -n tb_chip.vvp +late=${LATE:-0} | grep -vE "finish called")
