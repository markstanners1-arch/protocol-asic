// The whole chip (src/chip.v, unchanged) on the MachXO3L Starter Kit, wired to header J4.
// 12 MHz clock -> SPI host port up to 1.5 MHz (clk/8).
//
// J4 hole  ball  chip signal
//   3      K12   ui_in[0]  CS
//   5      M14   ui_in[2]  MOSI
//   7      L14   uo_out[0] MISO
//   9      M15   ui_in[1]  SCK
//  11,12   GND
//   4      K13   uo_out[1] IRQ
//   6      N14   uio[0]    engine pin 0 (UART out in the test)
//   8      N16   uio[1]    engine pin 1
//  10      M16   uio[2]    engine pin 2
//  13..17  L15 L16 K14 K16 K15   uio[3..7]  engine pins 3-7
//  18..20  J14 H14 J15           uo_out[2..4] engine pins 8-10
//  23..25  J16 H15 H16           uo_out[5..7] engine pins 11-13
//  26..30  G15 G16 F15 F16 E15   ui_in[3..7]  engine pins 15-19
// LEDs: P16 = IRQ, N15 = heartbeat (kit LEDs light when driven low).

`default_nettype none

module chip_mxo3 #(
    // Default build (5 Nov 2026): two engines without the serialiser or the CRC units, 4-word TX FIFOs (the v0.2 engines).
    // Two engines with them do not fit this board under -nolutram. "build.sh ser" builds one engine with them (see build.sh).
    parameter NENG     = 2,
    parameter SER0     = 0,
    parameter CRC      = 0,
    parameter TXDEPTH0 = 4
) (
    input  wire       clk,          // 12 MHz
    input  wire       cs_n, sck, mosi,
    output wire       miso, irq,
    inout  wire [7:0] uio,
    output wire [5:0] uo_hi,        // uo_out[7:2]
    input  wire [4:0] ui_hi,        // ui_in[7:3]
    output wire [1:0] led
);
    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge clk) if (!rst_n) por <= por + 1'b1;

    wire [7:0] uo_out, uio_out, uio_oe;
    protocol_chip #(.NENG(NENG), .SER0(SER0), .CRC(CRC), .TXDEPTH0(TXDEPTH0)) chip (   // two engines: four do not fit this board
        .ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out),
        .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(rst_n));

    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : t
        assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
    end endgenerate

    assign miso  = uo_out[0];
    assign irq   = uo_out[1];
    assign uo_hi = uo_out[7:2];

    reg [23:0] beat = 0;
    always @(posedge clk) beat <= beat + 1'b1;
    assign led = ~{beat[23], irq};
endmodule
