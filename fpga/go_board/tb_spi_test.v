// Simulates spi_test_top with an SPI host at a given speed (+half=N chip clocks per SCK half period).
// Random write/read-back on the scratch registers, a burst, the FIFO loop-back and the ID.
`timescale 1ns/1ps
module tb_spi_test;
    reg clk = 0; always #20 clk = ~clk;              // 25 MHz
    reg cs_n = 1, sck = 0, mosi = 0;
    wire miso;
    wire [3:0] led; wire [6:0] s1, s2;
    spi_test_top dut (.i_clk(clk), .pmod_cs(cs_n), .pmod_mosi(mosi), .pmod_miso(miso), .pmod_sck(sck), .o_led(led), .o_seg1(s1), .o_seg2(s2));
    integer HALF, errors = 0, checks = 0;
    real phase;
    task bitx(input b, output r); begin
        mosi = b; #(HALF*40.0 + phase);
        sck = 1; r = miso; #(HALF*40.0);
        sck = 0; end endtask
    task begin_(input [7:0] c); integer i; reg r; begin cs_n = 0; #200; for (i = 7; i >= 0; i = i - 1) bitx(c[i], r); end endtask
    task word(input [15:0] w, output [15:0] g); integer i; reg r; begin for (i = 15; i >= 0; i = i - 1) begin bitx(w[i], r); g[i] = r; end end endtask
    task end_; begin #200; cs_n = 1; #400; end endtask
    task wr(input e, input [5:0] a, input [15:0] w); reg [15:0] d; begin begin_({1'b0, e, a}); word(w, d); end_; end endtask
    task rd(input e, input [5:0] a, output [15:0] w); begin begin_({1'b1, e, a}); word(0, w); end_; end endtask
    task chk(input [15:0] got, input [15:0] want); begin checks = checks + 1; if (got !== want) errors = errors + 1; end endtask
    reg [15:0] v, g, exp [0:15];
    integer k, e, a;
    initial begin
        if (!$value$plusargs("half=%d", HALF)) HALF = 4;
        phase = 7.3;                                   // SCK not lined up with the chip clock
        #20000;
        rd(0, 6'h29, g); chk(g, 16'hA5C3);
        for (k = 0; k < 16; k = k + 1) exp[k] = 0;
        for (k = 0; k < 150; k = k + 1) begin
            e = $random & 1; a = $random & 7; v = $random;
            wr(e[0], a[5:0], v); exp[{e[0], a[2:0]}] = v;
            rd(e[0], a[5:0], g); chk(g, v);
        end
        begin_(8'h40); for (k = 0; k < 8; k = k + 1) begin word(16'h1000 + k, g); exp[8 + k] = 16'h1000 + k; end end_;
        begin_(8'hC0); for (k = 0; k < 8; k = k + 1) begin word(0, g); chk(g, exp[8 + k]); end end_;
        begin_(8'h26); for (k = 0; k < 4; k = k + 1) word(16'hBEE0 + k, g); end_;
        rd(0, 6'h28, g); chk(g, 4);
        begin_(8'hA7); for (k = 0; k < 4; k = k + 1) begin word(0, g); chk(g, 16'hBEE0 + k); end end_;
        rd(0, 6'h28, g); chk(g, 0);
        $display("SCK = 25 MHz / %0d = %0.2f MHz: %0d checks, %0d errors %s", 2*HALF, 25.0/(2*HALF), checks, errors, errors ? "FAIL" : "PASS");
        $finish;
    end
endmodule
