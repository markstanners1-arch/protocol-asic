#!/usr/bin/env bash
# Record the serialiser sending the chip test's Ethernet frame (test/tb_chip.v) for GTKWave: test/wave/ser_frame.vcd.
# The whole chip test runs as usual (its PASS/FAIL lines are printed); only the frame is recorded.
# Then: gtkwave test/wave/ser_frame.gtkw
cd "$(dirname "$0")/../.."
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
python test/gen_chip_test.py >/dev/null
SRCS="src/chip.v src/cluster.v src/host_spi.v src/engine.v src/serialiser.v src/receiver.v src/crc32.v src/prog_mem.v src/fifo_mem.v src/glitch_filter.v"
mkdir -p test/build
iverilog -g2012 -P tb_chip.NENG=3 -o test/build/tb_wave.vvp $SRCS test/tb_chip.v test/wave/ser_frame_dump.v &&
    (cd test/build && vvp -n tb_wave.vvp | grep -E "PASS|FAIL" | tail -3)
ls -la test/wave/ser_frame.vcd
