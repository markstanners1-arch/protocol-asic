// Co-simulation bench for glitch_filter (4 inputs). Reads filter_in.hex, writes the outputs every clock.
// filter_in.hex: ntests; per test: p, n, ncycles, then one word per clock (bits 3:0 = inputs).
`timescale 1ns/1ps
module tb_filter;
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n = 0; reg [3:0] p = 0, n = 0, in = 0; wire [3:0] out;
    glitch_filter #(.WIDTH(4)) dut (.clk(clk), .rst_n(rst_n), .p(p), .n(n), .in(in), .out(out));
    reg [31:0] mem [0:4194303];
    integer f, ptr, t, nt, nc, c;
    initial begin
        $readmemh("filter_in.hex", mem);
        f = $fopen("filter_out.txt", "w");
        ptr = 0; nt = mem[ptr]; ptr = ptr + 1;
        for (t = 0; t < nt; t = t + 1) begin
            p = mem[ptr]; n = mem[ptr+1]; nc = mem[ptr+2]; ptr = ptr + 3;
            @(negedge clk); rst_n = 0; in = 0; @(negedge clk); @(negedge clk); rst_n = 1;
            $fwrite(f, "T\n");
            for (c = 0; c < nc; c = c + 1) begin
                in = mem[ptr][3:0]; ptr = ptr + 1;
                @(negedge clk);
                $fwrite(f, "%h\n", out);
            end
        end
        $fclose(f); $finish;
    end
endmodule
