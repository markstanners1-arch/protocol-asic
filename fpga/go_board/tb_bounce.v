// Simulates bounce_top with a bouncing switch: press and release, each with a burst of bounces.
`timescale 1ns/1ps
module tb_bounce;
    reg clk = 0; always #20 clk = ~clk;         // 25 MHz
    reg [3:0] sw = 0; wire [3:0] led; wire tx;
    bounce_top dut (.i_clk(clk), .i_sw(sw), .o_led(led), .o_uart_tx(tx));
    // serial decoder: prints each line
    reg [8*40-1:0] line = 0; integer i; reg [7:0] c;
    initial forever begin
        @(negedge tx); repeat (108) @(posedge clk);
        for (i = 0; i < 8; i = i + 1) begin repeat (217) @(posedge clk); c[i] = tx; end
        repeat (217) @(posedge clk);
        if (c == 8'h0A) begin $display("serial: %0s", line); line = 0; end
        else if (c != 8'h0D) line = {line[8*39-1:0], c};
    end
    // a bouncy edge: n bounces of random length (1-40 us) then settle at level
    task bouncy(input lvl, input integer n);
        integer k;
        begin
            for (k = 0; k < n; k = k + 1) begin
                sw[0] = lvl;  #(1000 * (1 + ($urandom % 40)));
                sw[0] = !lvl; #(1000 * (1 + ($urandom % 20)));
            end
            sw[0] = lvl;
        end
    endtask
    initial begin
        #200_000;
        bouncy(1, 3); #40_000_000;                 // press with 3 bounces, hold 40 ms
        bouncy(0, 5); #40_000_000;                 // release with 5 bounces
        sw[1] = 1; #30_000_000; sw[1] = 0; #30_000_000;   // step the setting to 1 (~10 us)
        sw[1] = 1; #30_000_000; sw[1] = 0; #30_000_000;   // and to 2 (~82 us)
        bouncy(1, 4); #40_000_000;
        bouncy(0, 2); #40_000_000;
        $finish;
    end
endmodule
