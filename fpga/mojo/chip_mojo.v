// The whole chip (src/chip.v, unchanged) on the Mojo v3 (Spartan-6 XC6SLX9-2TQG144), IO Shield stacked on top.
// 50 MHz oscillator (the ASIC's own speed) -> SPI host port up to 6.25 MHz (clk/8).
// Parameters (set by build.sh through xst -generics):
//   NENG, SER0, CRC, TXDEPTH0   passed to protocol_chip. Default build: three v0.2 engines (ID 0x0023, no serialiser,
//                               no CRC units, 4-word TX FIFOs). "ser" build: the serialiser, CRC units, 64-word FIFO.
//   CLK40                       1: the chip runs at 40 MHz from a DCM_SP (CLKFX = 50 MHz x 4 / 5); the chip is held in
//                               reset until the DCM reports LOCKED. 0: the chip runs on the 50 MHz oscillator.
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

module chip_mojo #(
    parameter NENG     = 3,
    parameter SER0     = 0,
    parameter CRC      = 0,
    parameter TXDEPTH0 = 4,
    parameter CLK40    = 0
) (
    input  wire        clk_in,      // 50 MHz oscillator
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
    // chip clock: the oscillator, or 40 MHz from the DCM
    wire clk, dcm_locked;
    generate if (CLK40) begin : g_clk40
        wire clkfx;
        DCM_SP #(.CLKIN_PERIOD(20.0), .CLKFX_MULTIPLY(4), .CLKFX_DIVIDE(5), .CLK_FEEDBACK("NONE"),
                 .STARTUP_WAIT("FALSE")) dcm (
            .CLKIN(clk_in), .CLKFB(1'b0), .RST(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0), .PSCLK(1'b0), .DSSEN(1'b0),
            .CLKFX(clkfx), .LOCKED(dcm_locked),
            .CLK0(), .CLK90(), .CLK180(), .CLK270(), .CLK2X(), .CLK2X180(), .CLKDV(), .CLKFX180(), .PSDONE(),
            .STATUS());
        BUFG bufg (.I(clkfx), .O(clk));
    end else begin : g_clk50
        assign clk = clk_in;
        assign dcm_locked = 1'b1;
    end endgenerate

    // reset: two flip-flops to bring the button into the clock domain, then the chip is held in reset while the
    // button is down and for 256 clocks after power-up
    reg [1:0] btn = 2'b00;
    always @(posedge clk) btn <= {btn[0], rst_n & dcm_locked};
    reg [7:0] por = 8'd0;
    always @(posedge clk) if (!btn[1]) por <= 8'd0; else if (!(&por)) por <= por + 1'b1;
    wire chip_rst_n = &por;

    wire [7:0] uo_out, uio_out, uio_oe;
    protocol_chip #(.NENG(NENG), .SER0(SER0), .CRC(CRC), .TXDEPTH0(TXDEPTH0)) chip (
        .ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out),
        .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk), .rst_n(chip_rst_n),
        .rx_pad(rx_pad), .rx_fall(rx_fall));
    // the receive pin's falling-edge sample (on the ASIC a latch; here a falling-edge flip-flop)
    wire rx_pad;
    reg  rx_fall = 1'b0;
    always @(negedge clk) rx_fall <= rx_pad;

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
