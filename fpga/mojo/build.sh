#!/usr/bin/env bash
# Build the whole chip (src/, three engines) for the Mojo v3 with Xilinx ISE 14.7 under WSL, and (with "load") put it
# in the FPGA through the Mojo's USB loader. Volatile only: load.py is never given --flash here.
# From Windows:  wsl -d Ubuntu -- bash /mnt/d/ProtocolASIC/fpga/mojo/build.sh [load]
# Other top:     TOP=pin_finder (pin_finder.v + pin_finder.ucf).  Port: MOJO_PORT (default COM14).
# Leaves fpga/mojo/build/<name>.bin (chip.bin for the chip) and the ISE reports beside it.
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="${TOP:-chip_mojo}"
PART=xc6slx9-2-tqg144                       # the Mojo v3's part: XC6SLX9-2TQG144C
PORT="${MOJO_PORT:-COM14}"
if [ "$TOP" = chip_mojo ]; then
    NAME=chip; UCF="$HERE/chip.ucf"
    SRCS="$HERE/../../src/chip.v $HERE/../../src/host_spi.v $HERE/../../src/engine.v $HERE/../../src/prog_mem.v $HERE/../../src/glitch_filter.v $HERE/chip_mojo.v"
else
    NAME="$TOP"; UCF="$HERE/$TOP.ucf"; SRCS="$HERE/$TOP.v"
fi

source ~/Xilinx/14.7/ISE_DS/settings64.sh >/dev/null 2>&1
export XILINXD_LICENSE_FILE=/mnt/d/Tools/ise_dl/Xilinx.lic

W=~/mojo_build/$NAME                         # ISE works on the Linux disk; results are copied back
rm -rf "$W"; mkdir -p "$W"; cd "$W"
OUT="$HERE/build"; mkdir -p "$OUT"

fail() { echo "BUILD FAILED at $1 (log: $OUT/$1.log)"; cp "$1.log" "$OUT/" 2>/dev/null || true; grep -E "^ERROR" "$1.log" | head -20; exit 1; }
step() { local n="$1"; shift; echo "== $n"; "$@" > "$n.log" 2>&1 || fail "$n"; if grep -q "^ERROR" "$n.log"; then fail "$n"; fi; }

: > top.prj; for f in $SRCS; do echo "verilog work \"$f\"" >> top.prj; done
echo "run -ifn top.prj -ifmt mixed -top $TOP -ofn top.ngc -ofmt NGC -p $PART -opt_mode Speed -opt_level 1" > top.xst
step xst      xst -ifn top.xst
step ngdbuild ngdbuild -p $PART -uc "$UCF" top.ngc top.ngd
step map      map -p $PART -w -o top_map.ncd top.ngd top.pcf
step par      par -w top_map.ncd top.ncd top.pcf
step trce     trce -v 10 -fastpaths top.ncd top.pcf -o top.twr
step bitgen   bitgen -w -g Binary:Yes -g UnusedPin:PullNone top.ncd top.bit top.pcf
[ -s top.bin ] || { echo "BUILD FAILED: bitgen left no top.bin"; exit 1; }

cp top.bin "$OUT/$NAME.bin"; cp top.bit "$OUT/$NAME.bit"
cp xst.log map.log par.log top_map.mrp top.par top.twr "$OUT/" 2>/dev/null || true
for f in xst map par trce bitgen ngdbuild; do cp "$f.log" "$OUT/${NAME}_$f.log"; done

echo "== $PART utilisation (map report)"
grep -E "Number of Slice Registers:|Number of Slice LUTs:|used as Memory:|Number of occupied Slices:|Number of RAMB16BWERs:|Number of RAMB8BWERs:|Number of bonded IOBs:" top_map.mrp | sed 's/^ *//'
echo "== timing (trce)"
grep -E "Minimum period:|Timing errors:|Score:" top.twr | head -4
if grep -q "All constraints were met" top.par; then TIMING=met; else TIMING=FAILED; echo "TIMING NOT MET at 50 MHz"; fi
echo "timing at 50 MHz: $TIMING"
ls -l "$OUT/$NAME.bin"

if [ "$1" = load ]; then
    [ "$TIMING" = met ] || { echo "not loading: timing not met"; exit 1; }
    LP="$(wslpath -w "$HERE/load.py")"; BIN="$(wslpath -w "$OUT/$NAME.bin")"
    (cd /mnt/c && cmd.exe /c python "$LP" "$PORT" "$BIN") 2>&1 | tr -d '\r'
fi
exit 0
