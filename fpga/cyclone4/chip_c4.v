// The whole chip (src/chip.v, unchanged) on a Cyclone IV E board (EP4CE6), second-opinion toolchain (Quartus).
// Board clock 50 MHz (the ASIC's own speed) -> SPI host port up to 6.25 MHz (clk/8).
// Pin locations live in chip_c4.qsf (3 Nov 2026: the black EP4CE6E22C8N core board, right-hand header 38-72).
// Same port list as fpga/machxo3/chip_mxo3.v, so the ESP32 wiring plan carries over.

`default_nettype none

module chip_c4 (
    input  wire       clk,          // 50 MHz
    input  wire       cs_n, sck, mosi,
    output wire       miso, irq,
    inout  wire [7:0] uio,
    output wire [5:0] uo_hi,        // uo_out[7:2]  engine pins 8-13
    input  wire [4:0] ui_hi,        // ui_in[7:3]   engine pins 15-19
    output wire [1:0] led           // [0] IRQ, [1] heartbeat (most boards light LEDs when driven low)
);
    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge clk) if (!rst_n) por <= por + 1'b1;

    wire [7:0] uo_out, uio_out, uio_oe;
    protocol_chip #(.NENG(2)) chip (             // two engines: four do not fit this board
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

    reg [25:0] beat = 0;
    always @(posedge clk) beat <= beat + 1'b1;
    assign led = ~{beat[25], irq};
endmodule
