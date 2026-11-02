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

## Roadmap (11 weeks to 18 Jan 2027)

| Weeks | Stage | Done when |
|---|---|---|
| 1 (now) | Paper design: block diagram + instruction set (`docs/core_design.md`) | Mark has checked it and the open questions are settled |
| 2 | Python model of the core: runs our firmware exactly, clock by clock | UART TX firmware runs on the model and matches `uart_tx.v` bit for bit |
| 3-4 | Verilog core, tested against the Python model cycle by cycle | thousands of random programs agree between model and Verilog |
| 4-5 | Firmware: UART TX/RX, SPI, I2C, each with a model partner device | all three pass, plus the measuring features |
| 6-7 | Into the Tiny Tapeout template; synthesis and layout on GitHub; fit 6x4, meet timing | clean build, timing met with margin |
| 7-8 | FPGA on the bench, talking to real boards (ESP32/Arduino as the other end) | real UART, I2C and SPI traffic with a real device |
| 9 | Stretch: CAN or PS/2 or low-speed USB; tidy the docs | |
| 10 | Submit early (aim for 11 Jan, a week of slack) | |

Other work comes first; this fills the gaps.

## Progress

- 2 Nov 2026: fixed-function UART transmitter + self-checking test bench (the known-good reference).
  PASS on 46 bytes at two baud rates. Checked the test can fail: a broken stop bit and a
  bit time one clock short were both caught. Size: 123 cells (31 flip-flops), about 0.5% of the budget.
- 2 Nov 2026: bench board found: **Nandland Go Board** (iCE40 HX1K VQ100, 25 MHz, 1280 logic cells,
  16 block RAMs, USB serial on the same lead). `fpga/go_board/`: hello test sends
  "Hello from Gosforth Skies" at 115200 once a second (hold switch 1 for nonstop). Simulated: the decoded
  line is correct. Built: 149/1280 cells (11%), timing good to 124 MHz.
  **Flashed and working on the real board:** 5 s on COM5 = 5 clean lines, 135 characters, no errors.
  (Scripts: `flash.ps1`, `listen.ps1`, `check_driver.ps1`; run them from an ordinary PowerShell window.)
  Note: the whole two-engine chip won't fit a 1K part; the board tests one engine at a time.

## Flashing the Go Board (first time only)

iceprog/openFPGALoader talk to the board's FTDI chip through libusb, so on Windows
interface 0 of the "Dual RS232-HS" device needs the WinUSB driver (Zadig does this).
Leave interface 1 alone: that's the serial port we read the output on.
That's a driver change on the PC, so Mark does it himself. Then:

    fpga/go_board/build.sh prog
    # serial terminal (PuTTY etc.) on the board's COM port, 115200 8N1
