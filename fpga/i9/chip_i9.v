// The Tiny Tapeout chip as taped out (protocol_chip, NENG 4, CRC 0, TXDEPTH0 1024, serialiser and receiver on engine 0)
// on the Colorlight i9 v7.2 (ECP5 LFE5U-45F-6BG381) on the Muse Lab breakout.
// Sources: the Tiny Tapeout repository's src/ at the taped-out commit (build.sh extracts them); this file is the FPGA
// wrapper in place of project.v. Chip clock 40 MHz from the 25 MHz oscillator (P3) through an EHXPLLL (25 / 5 x 8 / 15).
// Program stores and the 1024-word buffer in block RAM (build.sh marks the program stores block RAM).
// Host port (CS, SCK, MOSI, MISO, IRQ), engine pins 0-7 (two-way), 8-13 (out) and 15-19 (in) on the headers: chip_i9.lpf.

`default_nettype none

module chip_i9 (
    input  wire       clk25,
    input  wire       rst_n_pin,        // pulled up; low resets the chip
    input  wire       cs_n, sck, mosi,  // host port
    output wire       miso,
    output wire       irq,
    input  wire [4:0] ui_hi,            // engine inputs 15-19 (ui_in[7:3])
    output wire [5:0] uo,               // engine outputs 8-13 (uo_out[7:2])
    inout  wire [7:0] uio,              // engine pins 0-7
    output wire       led               // heartbeat (about 0.6 Hz at 40 MHz)
);
    // ---- 40 MHz
    wire cclk, locked;
    (* FREQUENCY_PIN_CLKI="25" *) (* FREQUENCY_PIN_CLKOP="40" *)
    (* ICP_CURRENT="12" *) (* LPF_RESISTOR="8" *) (* MFG_ENABLE_FILTEROPAMP="1" *) (* MFG_GMCREF_SEL="2" *)
    EHXPLLL #(
        .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"), .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
        .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"), .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
        .CLKI_DIV(5), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(15), .CLKOP_CPHASE(7), .CLKOP_FPHASE(0),
        .FEEDBK_PATH("CLKOP"), .CLKFB_DIV(8)
    ) pll (
        .RST(1'b0), .STDBY(1'b0), .CLKI(clk25), .CLKOP(cclk), .CLKFB(cclk),
        .PHASESEL0(1'b0), .PHASESEL1(1'b0), .PHASEDIR(1'b1), .PHASESTEP(1'b1), .PHASELOADREG(1'b1),
        .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0), .LOCK(locked));

    // ---- reset: a power-on count once the PLL locks, and the reset pin (synchronised)
    reg [7:0] por = 8'd0;
    reg [1:0] rs  = 2'b00;
    always @(posedge cclk) begin
        if (!(&por) && locked) por <= por + 1'b1;
        rs <= {rs[0], rst_n_pin};
    end
    wire rst_n = (&por) & rs[1];

    // ---- the chip
    wire [7:0] uo_out, uio_out, uio_oe;
    wire rx_pad;
    reg  rx_fall = 1'b0;                        // the receive pin at the falling edge (a latch on the ASIC)
    always @(negedge cclk) rx_fall <= rx_pad;
    protocol_chip #(.NENG(4), .CRC(0), .TXDEPTH0(1024)) chip (
        .ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out),
        .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(cclk), .rst_n(rst_n), .rx_pad(rx_pad), .rx_fall(rx_fall));

    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : t
        assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
    end endgenerate

    assign miso = uo_out[0];
    assign irq  = uo_out[1];
    assign uo   = uo_out[7:2];

    reg [25:0] beat = 26'd0;
    always @(posedge cclk) beat <= beat + 1'b1;
    assign led = beat[25];
endmodule
