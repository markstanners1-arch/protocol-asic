// Test of the i9 wrapper (chip_i9.v) through its host port, the PLL replaced by a pass-through: the ID register reads
// 0x0024 (the taped-out chip), each of the four engines' CLKDIV takes a different value and reads it back, and IRQ is
// low with nothing pending. Run: bash fpga/i9/sim.sh (after bash fpga/i9/build.sh chip has extracted the sources).
`timescale 1ns/1ps
`default_nettype none

module EHXPLLL #(
    parameter PLLRST_ENA = "", INTFB_WAKE = "", STDBY_ENABLE = "", DPHASE_SOURCE = "",
    parameter OUTDIVIDER_MUXA = "", OUTDIVIDER_MUXB = "", OUTDIVIDER_MUXC = "", OUTDIVIDER_MUXD = "",
    parameter CLKI_DIV = 1, CLKOP_ENABLE = "", CLKOP_DIV = 1, CLKOP_CPHASE = 0, CLKOP_FPHASE = 0,
    parameter FEEDBK_PATH = "", CLKFB_DIV = 1
) (
    input wire RST, STDBY, CLKI, CLKFB, PHASESEL0, PHASESEL1, PHASEDIR, PHASESTEP, PHASELOADREG, PLLWAKESYNC, ENCLKOP,
    output wire CLKOP, LOCK
);
    assign CLKOP = CLKI;
    assign LOCK  = 1'b1;
endmodule

module tb_chip_i9;
    reg clk = 0; always #12.5 clk = ~clk;      // the chip clock itself (40 MHz) through the pass-through PLL
    reg cs_n = 1, sck = 0, mosi = 0;
    wire miso, irq, led;
    wire [5:0] uo;
    wire [7:0] uio;
    pullup pu[7:0] (uio);
    chip_i9 dut (.clk25(clk), .rst_n_pin(1'b1), .cs_n(cs_n), .sck(sck), .mosi(mosi), .miso(miso), .irq(irq),
                 .ui_hi(5'b11111), .uo(uo), .uio(uio), .led(led));

    localparam HALF = 8;               // SCK = clk/16
    integer errors = 0;
    task spi_bit(input b, output r);
        begin mosi = b; repeat (HALF) @(posedge clk); sck = 1; r = miso; repeat (HALF) @(posedge clk); sck = 0; end
    endtask
    task spi_word(input [15:0] w, output [15:0] got);
        integer i; reg r;
        begin for (i = 15; i >= 0; i = i - 1) begin spi_bit(w[i], r); got[i] = r; end end
    endtask
    task xfer(input [15:0] cmd, input [15:0] w, output [15:0] got);
        reg [15:0] d;
        begin
            cs_n = 0; repeat (HALF) @(posedge clk);
            spi_word(cmd, d); spi_word(w, got);
            repeat (HALF) @(posedge clk); cs_n = 1; repeat (2 * HALF) @(posedge clk);
        end
    endtask
    task check(input [255:0] what, input [15:0] got, input [15:0] want);
        begin
            if (got !== want) begin $display("FAIL: %0s = 0x%h, expected 0x%h", what, got, want); errors = errors + 1; end
            else $display("ok:   %0s = 0x%h", what, got);
        end
    endtask

    reg [15:0] w;
    integer e;
    initial begin
        repeat (400) @(posedge clk);                                   // past the 255-clock power-on count
        xfer({1'b1, 3'd0, 6'd0, 6'h2A}, 16'd0, w); check("ID", w, 16'h0024);
        for (e = 0; e < 4; e = e + 1) xfer({1'b0, e[2:0], 6'd0, 6'h21}, 16'h0100 + 7 * e, w);
        for (e = 0; e < 4; e = e + 1) begin
            xfer({1'b1, e[2:0], 6'd0, 6'h21}, 16'd0, w); check("engine CLKDIV read back", w, 16'h0100 + 7 * e);
        end
        check("IRQ with nothing pending", {15'd0, irq}, 16'd0);
        if (errors) $display("FAIL (%0d)", errors); else $display("PASS");
        $finish;
    end
endmodule
