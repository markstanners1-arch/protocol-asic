// Feeds uart_tx.v back to back from test/build/bytes.hex and writes the TX line,
// one character per system clock, to tx_trace.txt. Used by model/compare_uart.py.
`timescale 1ns/1ps
`default_nettype none
module tb_uart_dump;
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n = 0;
    reg [15:0] divisor;
    reg [7:0] mem [0:4095];
    integer nbytes, i, f, cycles;
    reg [7:0] data = 0; reg start = 0;
    wire tx, busy;
    uart_tx dut (.clk(clk), .rst_n(rst_n), .divisor(divisor), .data(data), .start(start), .tx(tx), .busy(busy));
    always @(posedge clk) $fwrite(f, "%b", tx);
    initial begin
        if (!$value$plusargs("divisor=%d", divisor)) divisor = 7;
        if (!$value$plusargs("n=%d", nbytes)) nbytes = 0;
        $readmemh("bytes.hex", mem);
        f = $fopen("tx_trace.txt", "w");
        repeat (3) @(posedge clk); rst_n <= 1;
        for (i = 0; i < nbytes; i = i + 1) begin
            @(posedge clk); while (busy || start) @(posedge clk);
            data <= mem[i]; start <= 1; @(posedge clk); start <= 0;
        end
        @(posedge clk); while (busy) @(posedge clk);
        repeat (20) @(posedge clk);
        $fclose(f); $finish;
    end
endmodule
