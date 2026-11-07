// Co-simulation bench: runs a batch of tests from cosim_in.hex through engine.v and writes
// the engine's full state after every clock to cosim_out.txt. model/cosim.py writes the input,
// runs the Python model on the same tests and compares the two, line by line.
//
// Two engines are driven with the same stimulus: dut0 with the serialiser and the 64-word TX FIFO (engine 0 of the
// chip), dut1 without (engines 1 and 2); each test's `kind` word says which one's state is written out.
//
// cosim_in.hex (32-bit hex words):
//   ntests
//   per test: ncycles, 32 program words, 22 config words, then per cycle: pins, push, pop
//   (push = bit 16 valid, bits 15:0 data; pop = bit 0)
// cosim_out.txt: per test "T <n>", then per cycle one line of state (see the $fwrite below).

`timescale 1ns/1ps
`default_nettype none

module tb_cosim;
    parameter CRC = 1;                  // 0: both engines built without the CRC unit (model/cosim.py, CRC=0)
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
    reg [12:0] cfg_sercfg;
    reg [15:0] cfg_serdiv;
    reg [31:0] cfg_crcpoly, cfg_crcinit;
    reg        kind;
    reg        imem_we = 0;
    reg [4:0]  imem_addr = 0;
    reg [15:0] imem_wdata = 0;
    reg        host_push = 0, host_pop = 0;
    reg [15:0] host_push_data = 0;
    reg [31:0] pins_in = 0;

    wire [15:0] host_pop_data [0:1];
    wire [6:0]  tx_level [0:1];
    wire [2:0]  rx_level [0:1];
    wire [31:0] out_val [0:1], out_dir [0:1], crc [0:1];
    wire [4:0]  pc [0:1], osr_count [0:1], isr_count [0:1], delay [0:1];
    wire [15:0] x [0:1], y [0:1], osr [0:1], isr [0:1], sw [0:1];
    wire        sw_run [0:1], ser_busy [0:1], ser_under [0:1];

    genvar g;
    generate for (g = 0; g < 2; g = g + 1) begin : duts
        engine #(.SER(g == 0 ? 1 : 0), .TXDEPTH(g == 0 ? 64 : 4), .CRC(CRC)) dut (
            .clk(clk), .rst_n(rst_n),
            .cfg_clkdiv(cfg_clkdiv), .cfg_start(cfg_start), .cfg_wrap_bottom(cfg_wrap_bottom), .cfg_wrap_top(cfg_wrap_top),
            .cfg_out_base(cfg_out_base), .cfg_out_count(cfg_out_count), .cfg_set_base(cfg_set_base), .cfg_set_count(cfg_set_count),
            .cfg_side_base(cfg_side_base), .cfg_side_count(cfg_side_count), .cfg_side_opt(cfg_side_opt), .cfg_side_dir(cfg_side_dir),
            .cfg_in_base(cfg_in_base), .cfg_jmp_pin(cfg_jmp_pin), .cfg_out_right(cfg_out_right), .cfg_in_right(cfg_in_right),
            .cfg_fault_addr(cfg_fault_addr),
            .cfg_sercfg(cfg_sercfg), .cfg_serdiv(cfg_serdiv), .cfg_crcpoly(cfg_crcpoly), .cfg_crcinit(cfg_crcinit),
            .imem_we(imem_we), .imem_addr(imem_addr), .imem_wdata(imem_wdata),
            .host_push(host_push), .host_push_data(host_push_data), .host_pop(host_pop), .host_pop_data(host_pop_data[g]),
            .tx_level(tx_level[g]), .rx_level(rx_level[g]),
            .pins_in(pins_in), .out_val(out_val[g]), .out_dir(out_dir[g]),
            .ser_busy(ser_busy[g]), .ser_under(ser_under[g]), .crc(crc[g]),
            .pc(pc[g]), .x(x[g]), .y(y[g]), .osr(osr[g]), .osr_count(osr_count[g]), .isr(isr[g]), .isr_count(isr_count[g]),
            .delay(delay[g]), .sw(sw[g]), .sw_run(sw_run[g]));
    end endgenerate

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
            kind = mem[p+17]; cfg_sercfg = mem[p+18]; cfg_serdiv = mem[p+19]; cfg_crcpoly = mem[p+20]; cfg_crcinit = mem[p+21];
            p = p + 22;
            @(negedge clk); @(negedge clk);       // reset sees the config
            rst_n = 1;
            $fwrite(f, "T %0d\n", t);
            for (c = 0; c < ncycles; c = c + 1) begin
                pins_in = mem[p];
                host_push = mem[p+1][16]; host_push_data = mem[p+1][15:0];
                host_pop = mem[p+2][0];
                p = p + 3;
                #1;
                popped_ok = host_pop && (rx_level[kind] != 0);
                popped = host_pop_data[kind];
                @(negedge clk);
                // pc x y osr osr_count isr isr_count delay sw sw_run pins_out out_dir tx rx popped busy under crc
                $fwrite(f, "%0d %h %h %h %0d %h %0d %0d %h %0d %h %h %0d %0d %s %0d %0d %h\n",
                        pc[kind], x[kind], y[kind], osr[kind], osr_count[kind], isr[kind], isr_count[kind], delay[kind],
                        sw[kind], sw_run[kind], out_val[kind], out_dir[kind],
                        tx_level[kind], rx_level[kind], popped_ok ? $sformatf("%h", popped) : "-",
                        ser_busy[kind], ser_under[kind], crc[kind]);
            end
        end
        $fclose(f);
        $finish;
    end
endmodule
