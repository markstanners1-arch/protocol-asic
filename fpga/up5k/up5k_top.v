// Fit test for an iCE40 UP5K board (e.g. iCESugar): the whole chip with real two-way uio pins.
`default_nettype none
module up5k_top (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    inout  wire [7:0] uio
);
    wire [7:0] uio_out, uio_oe;
    protocol_chip chip (.ui_in(ui_in), .uo_out(uo_out), .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
                        .ena(1'b1), .clk(clk), .rst_n(rst_n),
        .rx_pad(rx_pad), .rx_fall(rx_fall));
    // the receive pin's falling-edge sample (on the ASIC a latch; here a falling-edge flip-flop)
    wire rx_pad;
    reg  rx_fall = 1'b0;
    always @(negedge clk) rx_fall <= rx_pad;
    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : t
        assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
    end endgenerate
endmodule
