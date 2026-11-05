#!/usr/bin/env bash
# Build the whole chip (src/) for the Mojo v3 with Xilinx ISE 14.7 under WSL, and (with "load") put it in the FPGA
# through the Mojo's USB loader. Volatile only: load.py is never given --flash here.
# From Windows:  wsl -d Ubuntu -- bash /mnt/d/ProtocolASIC/fpga/mojo/build.sh [ser] [clk40] [load]
#   (no option)  build/chip.bin       three engines (ID 0x0023), v0.2 engines: no serialiser, no CRC units, 4-word TX FIFOs
#                                     (NENG=3 SER0=0 CRC=0 TXDEPTH0=4), chip clock 50 MHz
#   ser          build/chip_ser.bin   engine 0 with the serialiser and the 64-word TX FIFO, a CRC unit on every engine
#                                     (SER0=1 CRC=1 TXDEPTH0=64), NENG=2 (ID 0x0022; SER_NENG=1 for one engine)
#   clk40        adds _40 to the name: the chip clock is 40 MHz from a DCM (chip_mojo.v CLK40=1)
#   MOJO="NAME=value ..." sets the wrapper's parameters by hand, on top of the build chosen.
# Other top:     TOP=pin_finder (pin_finder.v + pin_finder.ucf).  Port: MOJO_PORT (default COM14).
# Leaves fpga/mojo/build/<name>.bin and the ISE reports beside it.
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOP="${TOP:-chip_mojo}"
PART=xc6slx9-2-tqg144                       # the Mojo v3's part: XC6SLX9-2TQG144C
PORT="${MOJO_PORT:-COM14}"
NAME=chip; G="NENG=3 SER0=0 CRC=0 TXDEPTH0=4"; MHZ=50; LOAD=""
for a in "$@"; do
    case "$a" in
        ser)   NAME=chip_ser; G="NENG=${SER_NENG:-2} SER0=1 CRC=1 TXDEPTH0=64" ;;
        clk40) C40=1 ;;
        load)  LOAD=1 ;;
        *)     echo "unknown option $a (ser, clk40, load)"; exit 1 ;;
    esac
done
[ -n "$C40" ] && { NAME="${NAME}_40"; G="$G CLK40=1"; MHZ=40; }
G="$G $MOJO"
S="$HERE/../../src"
if [ "$TOP" = chip_mojo ]; then
    UCF="$HERE/chip.ucf"
    SRCS="$S/chip.v $S/cluster.v $S/host_spi.v $S/engine.v $S/serialiser.v $S/crc32.v $S/prog_mem.v $S/glitch_filter.v $HERE/chip_mojo.v"
    GEN="-generics {$(echo $G)}"
else
    NAME="$TOP"; UCF="$HERE/$TOP.ucf"; SRCS="$HERE/$TOP.v"; GEN=""; G=""
fi
echo "== $NAME: $G"

set --                                       # settings64.sh reads $1 when sourced
source ~/Xilinx/14.7/ISE_DS/settings64.sh >/dev/null 2>&1
export XILINXD_LICENSE_FILE=/mnt/d/Tools/ise_dl/Xilinx.lic

W=~/mojo_build/$NAME                         # ISE works on the Linux disk; results are copied back
rm -rf "$W"; mkdir -p "$W"; cd "$W"
OUT="$HERE/build"; mkdir -p "$OUT"

fail() { echo "BUILD FAILED at $1 (log: $OUT/$1.log)"; cp "$1.log" "$OUT/" 2>/dev/null || true; grep -E "^ERROR" "$1.log" | head -20; exit 1; }
step() { local n="$1"; shift; echo "== $n"; "$@" > "$n.log" 2>&1 || fail "$n"; if grep -q "^ERROR" "$n.log"; then fail "$n"; fi; }

: > top.prj; for f in $SRCS; do echo "verilog work \"$f\"" >> top.prj; done
echo "run -ifn top.prj -ifmt mixed -top $TOP -ofn top.ngc -ofmt NGC -p $PART -opt_mode Speed -opt_level 1 $GEN" > top.xst
step xst      xst -ifn top.xst
step ngdbuild ngdbuild -p $PART -uc "$UCF" top.ngc top.ngd
step map      map -p $PART -w -o top_map.ncd top.ngd top.pcf
step par      par -w top_map.ncd top.ncd top.pcf
step trce     trce -v 10 -fastpaths top.ncd top.pcf -o top.twr
step bitgen   bitgen -w -g Binary:Yes -g UnusedPin:PullNone top.ncd top.bit top.pcf
[ -s top.bin ] || { echo "BUILD FAILED: bitgen left no top.bin"; exit 1; }

cp top.bin "$OUT/$NAME.bin"; cp top.bit "$OUT/$NAME.bit"
cp top_map.mrp "$OUT/$NAME.mrp"; cp top.par "$OUT/$NAME.par"; cp top.twr "$OUT/$NAME.twr"
for f in xst map par trce bitgen ngdbuild; do cp "$f.log" "$OUT/${NAME}_$f.log"; done

echo "== $PART utilisation (map report)"
grep -E "Number of Slice Registers:|Number of Slice LUTs:|used as Memory:|Number of occupied Slices:|Number of RAMB16BWERs:|Number of RAMB8BWERs:|Number of bonded IOBs:" top_map.mrp | sed 's/^ *//'
echo "== timing (trce)"
grep -E "Minimum period:|Timing errors:|Score:" top.twr | head -4
if grep -q "All constraints were met" top.par; then TIMING=met; else TIMING=FAILED; echo "TIMING NOT MET"; fi
echo "timing (chip clock $MHZ MHz): $TIMING"
ls -l "$OUT/$NAME.bin"

if [ -n "$LOAD" ]; then
    [ "$TIMING" = met ] || { echo "not loading: timing not met"; exit 1; }
    LP="$(wslpath -w "$HERE/load.py")"; BIN="$(wslpath -w "$OUT/$NAME.bin")"
    (cd /mnt/c && cmd.exe /c python "$LP" "$PORT" "$BIN") 2>&1 | tr -d '\r'
fi
exit 0
