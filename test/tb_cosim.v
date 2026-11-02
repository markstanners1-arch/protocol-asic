// Co-simulation bench: runs a batch of tests from cosim_in.hex through engine.v and writes
// the engine's full state after every clock to cosim_out.txt. model/cosim.py writes the input,
// runs the Python model on the same tests and compares the two, line by line.
//
// cosim_in.hex (32-bit hex words):
//   ntests
//   per test: ncycles, 32 program words, 16 config words, then per cycle: pins, push, pop
//   (push = bit 16 valid, bits 15:0 data; pop = bit 0)
// cosim_out.txt: per test "T <n>", then per cycle one line of state (see the $fwrite below).

`timescale 1ns/1ps
`default_nettype none

module tb_cosim;
    reg clk = 0;
    reg rst_n = 0;

    reg [15:0] cfg_clkdiv;
    reg [4:0]  cfg_start, cfg_wrap_bottom, cfg_wrap_top, cfg_out_base, cfg_out_count, cfg_set_base;
    reg [2:0]  cfg_set_count;
    reg [4:0]  cfg_side_base;
    reg [1:0]  cfg_side_count;
    reg        cfg_side_opt, cfg_side_dir;
    reg [4:0]  cfg_in_base, cfg_jmp_pin;
    reg        cfg_out_right, cfg_in_right;
    reg [4:0]  cfg_fault_addr;
    reg        imem_we = 0;
    reg [4:0]  imem_addr = 0;
    reg [15:0] imem_wdata = 0;
    reg        host_push = 0, host_pop = 0;
    reg [15:0] host_push_data = 0;
    wire [15:0] host_pop_data;
    wire [2:0] tx_level, rx_level;
    reg [31:0] pins_in = 0;
    wire [31:0] out_val, out_dir;
    wire [4:0] pc, osr_count, isr_count, delay;
    wire [15:0] x, y, osr, isr, sw;
    wire sw_run;

    engine dut (
        .clk(clk), .rst_n(rst_n),
        .cfg_clkdiv(cfg_clkdiv), .cfg_start(cfg_start), .cfg_wrap_bottom(cfg_wrap_bottom), .cfg_wrap_top(cfg_wrap_top),
        .cfg_out_base(cfg_out_base), .cfg_out_count(cfg_out_count), .cfg_set_base(cfg_set_base), .cfg_set_count(cfg_set_count),
        .cfg_side_base(cfg_side_base), .cfg_side_count(cfg_side_count), .cfg_side_opt(cfg_side_opt), .cfg_side_dir(cfg_side_dir),
        .cfg_in_base(cfg_in_base), .cfg_jmp_pin(cfg_jmp_pin), .cfg_out_right(cfg_out_right), .cfg_in_right(cfg_in_right),
        .cfg_fault_addr(cfg_fault_addr),
        .imem_we(imem_we), .imem_addr(imem_addr), .imem_wdata(imem_wdata),
        .host_push(host_push), .host_push_data(host_push_data), .host_pop(host_pop), .host_pop_data(host_pop_data),
        .tx_level(tx_level), .rx_level(rx_level),
        .pins_in(pins_in), .out_val(out_val), .out_dir(out_dir),
        .pc(pc), .x(x), .y(y), .osr(osr), .osr_count(osr_count), .isr(isr), .isr_count(isr_count),
        .delay(delay), .sw(sw), .sw_run(sw_run));

    always #5 clk = ~clk;

    reg [31:0] mem [0:2097151];
    integer p, f, t, ntests, ncycles, i, c;
    reg [15:0] popped;
    reg        popped_ok;

    initial begin
        $readmemh("cosim_in.hex", mem);
        f = $fopen("cosim_out.txt", "w");
        p = 0;
        ntests = mem[p]; p = p + 1;
        for (t = 0; t < ntests; t = t + 1) begin
            ncycles = mem[p]; p = p + 1;
            // hold reset, load the program
            @(negedge clk); rst_n = 0; host_push = 0; host_pop = 0; pins_in = 0;
            for (i = 0; i < 32; i = i + 1) begin
                imem_we = 1; imem_addr = i; imem_wdata = mem[p + i][15:0];
                @(negedge clk);
            end
            imem_we = 0; p = p + 32;
            cfg_clkdiv = mem[p+0]; cfg_start = mem[p+1]; cfg_wrap_bottom = mem[p+2]; cfg_wrap_top = mem[p+3];
            cfg_out_base = mem[p+4]; cfg_out_count = mem[p+5]; cfg_set_base = mem[p+6]; cfg_set_count = mem[p+7];
            cfg_side_base = mem[p+8]; cfg_side_count = mem[p+9]; cfg_side_opt = mem[p+10]; cfg_side_dir = mem[p+11];
            cfg_in_base = mem[p+12]; cfg_jmp_pin = mem[p+13]; cfg_out_right = mem[p+14]; cfg_in_right = mem[p+15];
            cfg_fault_addr = mem[p+16];
            p = p + 17;
            @(negedge clk); @(negedge clk);       // reset sees the config
            rst_n = 1;
            $fwrite(f, "T %0d\n", t);
            for (c = 0; c < ncycles; c = c + 1) begin
                pins_in = mem[p];
                host_push = mem[p+1][16]; host_push_data = mem[p+1][15:0];
                host_pop = mem[p+2][0];
                p = p + 3;
                #1;
                popped_ok = host_pop && (rx_level != 0);
                popped = host_pop_data;
                @(negedge clk);
                // pc x y osr osr_count isr isr_count delay sw sw_run out_val out_dir tx rx popped
                $fwrite(f, "%0d %h %h %h %0d %h %0d %0d %h %0d %h %h %0d %0d %s\n",
                        pc, x, y, osr, osr_count, isr, isr_count, delay, sw, sw_run, out_val, out_dir,
                        tx_level, rx_level, popped_ok ? $sformatf("%h", popped) : "-");
            end
        end
        $fclose(f);
        $finish;
    end
endmodule
