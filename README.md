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

Needs Icarus Verilog (from the OSS CAD Suite).

    iverilog -g2012 -o build/uart_tx.vvp src/uart_tx.v test/tb_uart_tx.v
    vvp build/uart_tx.vvp

## Progress

- 2 Nov 2026: fixed-function UART transmitter + self-checking test bench (the known-good reference).
