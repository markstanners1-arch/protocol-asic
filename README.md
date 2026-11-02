# Protocol emulator ASIC

Our entry for Jane Street's protocol emulator ASIC competition
(https://blog.janestreet.com/protocol-emulator-asic-competition/).

- Process: IHP 130 nm CMOS5L via Tiny Tapeout, 6x4 tiles (about 24K logic cells)
- Must do: UART, SPI, I2C in firmware on a small programmable core
- Stretch: low-speed USB, 10 Mbit Ethernet; also CAN, PS/2, JTAG, SWD
- Deadline: 18 January 2027 (target shuttle: March 2027)
- Team: Mark Stanners + Claude

## Layout

- `src/`  Verilog design
- `test/` test benches
- `docs/` notes and design decisions

## Run the tests

Tools: OSS CAD Suite 2026-11-02, unpacked at `D:\Tools\oss-cad-suite`
(Icarus Verilog, Verilator, Yosys, nextpnr, GTKWave). From Git Bash:

    ./run.sh test     # simulate every test bench, prints PASS/FAIL
    ./run.sh size     # rough cell count per module
    D:/Tools/oss-cad-suite/bin/gtkwave build/uart_tx.vcd   # look at the waveform

## Progress

- 2 Nov 2026: fixed-function UART transmitter + self-checking test bench (the known-good reference).
  PASS on 46 bytes at two baud rates. Checked the test can fail: a broken stop bit and a
  bit time one clock short were both caught. Size: 123 cells (31 flip-flops), about 0.5% of the budget.
