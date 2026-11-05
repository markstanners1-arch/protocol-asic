// The whole chip (src/chip.v, unchanged) on the Mojo v3 (Spartan-6 XC6SLX9-2TQG144), IO Shield stacked on top.
// 50 MHz oscillator (the ASIC's own speed) -> SPI host port up to 6.25 MHz (clk/8). Three engines: ID reads 0x0023.
// Pin locations and the reasons for them are in chip.ucf. In short (FPGA pin numbers, as printed beside the
// shield's header rows):
//   host CS, SCK, MOSI     P50 P51 P40              (right header, rows 50 and 40: free of shield devices)
//   engine pins 0-7        P41 P34 P35 P32 P33 P29 P30 P27   (two-way, pull-ups; free of shield devices)
//   host MISO, IRQ         P134 P133                (the Mojo's LED0 and LED1 pins)
//   engine pins 8-13       P132 P131 P127 P126 P124 P123     (the Mojo's LED2-LED7 pins: each LED shows its pin)
//   engine pins 15-19      P57 P58 P66 P67 P74      (shield DIP switch pins, pull-downs: switches OFF to use a lead)
// The Mojo's own eight LEDs therefore show MISO, IRQ and engine pins 8-13 as they are driven.
// IO Shield: LED bank io_led[7:0] = engine pins 0-7 as the pads read, [15:8] = which of pins 0-7 an engine drives,
// [20:16] = engine pins 15-19, [21] = host CS active, [22] = reset held, [23] = heartbeat. 7-segment display off.
// Reset: the Mojo's reset button (rst_n, P38, low when pressed), synchronised, plus a power-on count.

`default_nettype none

module chip_mojo (
    input  wire        clk,         // 50 MHz
    input  wire        rst_n,       // reset button, active low
    input  wire        cs_n, sck, mosi,
    output wire        miso, irq,
    inout  wire [7:0]  uio,         // engine pins 0-7
    output wire [5:0]  uo_hi,       // uo_out[7:2]  engine pins 8-13
    input  wire [4:0]  ui_hi,       // ui_in[7:3]   engine pins 15-19
    output wire [23:0] io_led,
    output wire [7:0]  io_seg,
    output wire [3:0]  io_sel
);
    // reset: two flip-flops to bring the button into the clock domain, then the chip is held in reset while the
    // button is down and for 256 clocks after power-up
    reg [1:0] btn = 2'b00;
    always @(posedge clk) btn <= {btn[0], rst_n};
    reg [7:0] por = 8'd0;
    always @(posedge clk) if (!btn[1]) por <= 8'd0; else if (!(&por)) por <= por + 1'b1;
    wire chip_rst_n = &por;

    wire [7:0] uo_out, uio_out, uio_oe;
    protocol_chip #(.NENG(3)) chip (
        .ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out),
        .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(chip_rst_n));

    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : t
        assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
    end endgenerate

    assign miso  = uo_out[0];
    assign irq   = uo_out[1];
    assign uo_hi = uo_out[7:2];

    reg [25:0] beat = 0;
    always @(posedge clk) beat <= beat + 1'b1;
    assign io_led = {beat[25], ~chip_rst_n, ~cs_n, ui_hi, uio_oe, uio};
    assign io_seg = 8'hFF;          // segments and digit selects are active low: all off
    assign io_sel = 4'hF;
endmodule
