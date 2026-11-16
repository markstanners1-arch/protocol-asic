"""Load a bitstream into the Mojo v3 (Spartan-6 LX9) through its on-board ATmega32U4, which the board's stock firmware
turns into a loader on a USB serial port. Protocol from Embedded Micro's mojo-arduino firmware (mojo_loader.ino):
the PC toggles DTR to reset the AVR into load mode, then sends one command byte, the bitstream size as four
little-endian bytes, and the bitstream. 'R' puts it straight into the FPGA (lost at power off); 'V' writes the flash
and verifies ('S' reads it back, 'L' loads the FPGA from it), so the board boots into it from then on.

    python fpga/mojo/load.py COM14 build/chip.bin          # into the FPGA only (the usual bench load)
    python fpga/mojo/load.py COM14 build/chip.bin --flash  # into the flash, verified, and loaded

The .bin comes from bitgen with -g Binary:Yes. 5 Nov 2026."""
import sys, time, argparse
import serial

ap = argparse.ArgumentParser()
ap.add_argument("port"); ap.add_argument("bin"); ap.add_argument("--flash", action="store_true")
a = ap.parse_args()
data = open(a.bin, "rb").read()
print("%s: %d bytes -> %s via %s" % (a.bin, len(data), "flash" if a.flash else "FPGA RAM", a.port))

ser = serial.Serial(a.port, 115200, timeout=10)
try:
    for _ in range(5):                      # reset the AVR into its loader
        ser.dtr = False; time.sleep(0.005)
        ser.dtr = True;  time.sleep(0.005)
    time.sleep(1.0)
    ser.reset_input_buffer()

    def expect(c, what):
        got = ser.read(1)
        if got != c:
            raise SystemExit("FAIL: %s: expected %r, got %r" % (what, c, got))

    ser.write(b"V" if a.flash else b"R"); expect(b"R", "ready")
    ser.write(bytes((len(data) >> (8 * i)) & 0xFF for i in range(4))); expect(b"O", "size")
    for i in range(0, len(data), 256):
        ser.write(data[i:i + 256])
    ser.flush()
    expect(b"D", "data")
    if a.flash:
        ser.write(b"S")
        if ser.read(1) != b"\xAA":
            raise SystemExit("FAIL: flash has no valid marker")
        size = int.from_bytes(ser.read(4), "little")
        if size != len(data) + 5:
            raise SystemExit("FAIL: flash size %d, expected %d" % (size, len(data) + 5))
        back = b""
        while len(back) < len(data):
            chunk = ser.read(min(256, len(data) - len(back)))
            if not chunk:
                raise SystemExit("FAIL: verify read timed out at %d of %d" % (len(back), len(data)))
            back += chunk
        if back != data:
            bad = next(i for i in range(len(data)) if back[i] != data[i])
            raise SystemExit("FAIL: verify mismatch at byte %d" % bad)
        ser.write(b"L"); expect(b"D", "load from flash")
        print("PASS: written, verified and loaded")
    else:
        print("PASS: loaded")
finally:
    ser.close()
