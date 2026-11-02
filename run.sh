#!/usr/bin/env bash
# Run the tests and a quick size check.
#   ./run.sh test    simulate every test/tb_*.v (PASS/FAIL)
#   ./run.sh size    rough cell count from a generic yosys synthesis
# Needs the OSS CAD Suite on PATH (D:\Tools\oss-cad-suite).
set -e
cd "$(dirname "$0")"
export PATH="/d/Tools/oss-cad-suite/bin:/d/Tools/oss-cad-suite/lib:$PATH"
mkdir -p build

case "${1:-test}" in
  test)
    for tb in test/tb_*.v; do
      name=$(basename "$tb" .v)
      iverilog -g2012 -Wall -o "build/$name.vvp" src/*.v "$tb"
      (cd build && vvp -n "$name.vvp")
    done
    ;;
  size)
    for f in src/*.v; do
      top=$(basename "$f" .v)
      echo "== $top"
      yosys -q -p "read_verilog $f; synth -top $top -flatten; abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX; tee -q -o build/stat_$top.txt stat" >/dev/null
      grep -E "^ +[0-9]+ +(cells|  \\$)" "build/stat_$top.txt"
      echo "   (budget: about 24,000 cells for 6x4 tiles)"
    done
    ;;
esac
