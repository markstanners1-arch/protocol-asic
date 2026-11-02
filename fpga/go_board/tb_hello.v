// Simulates hello_top and decodes the serial line like a PC terminal would.
`timescale 1ns/1ps
module tb_hello;
    reg clk = 0; always #20 clk = ~clk;          // 25 MHz
    reg [3:0] sw = 0; wire [3:0] led; wire tx;
    hello_top dut (.i_clk(clk), .i_sw(sw), .o_led(led), .o_uart_tx(tx));
    integer i; reg [7:0] c; reg [8*40-1:0] line = 0;
    initial begin
        forever begin
            @(negedge tx); repeat (108) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin repeat (217) @(posedge clk); c[i] = tx; end
            repeat (217) @(posedge clk);
            if (tx !== 1) $display("FAIL: bad stop bit");
            if (c == 8'h0A) begin $display("Terminal shows: %0s", line); $finish; end
            else if (c != 8'h0D) line = {line[8*39-1:0], c};
        end
    end
    initial begin #20_000_000 $display("FAIL: no complete line"); $finish; end
endmodule
