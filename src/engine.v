// One protocol engine, built from docs/isa.md (v0.1).
// Checked against the Python model (model/engine.py) every system clock by model/cosim.py.
//
// In 74-series terms: a 16-bit clock divider, a 5-bit program counter, two 16-bit
// loadable down-counters (X, Y), two 16-bit shift registers (OSR out, ISR in) with bit counters,
// a 5-bit delay counter, a 16-bit stopwatch, two 4-word FIFOs, a 2-flip-flop synchroniser
// on every input, and a 32 x 16 program memory. One instruction per engine tick.

`timescale 1ns/1ps
`default_nettype none

module engine (
    input  wire        clk,
    input  wire        rst_n,

    // configuration (set by the host, held steady while running)
    input  wire [15:0] cfg_clkdiv,
    input  wire [4:0]  cfg_start,
    input  wire [4:0]  cfg_wrap_bottom,
    input  wire [4:0]  cfg_wrap_top,
    input  wire [4:0]  cfg_out_base,
    input  wire [4:0]  cfg_out_count,     // 0-16
    input  wire [4:0]  cfg_set_base,
    input  wire [2:0]  cfg_set_count,     // 0-5
    input  wire [4:0]  cfg_side_base,
    input  wire [1:0]  cfg_side_count,    // 0-2
    input  wire        cfg_side_opt,
    input  wire [4:0]  cfg_in_base,
    input  wire [4:0]  cfg_jmp_pin,
    input  wire        cfg_out_right,
    input  wire        cfg_in_right,
    input  wire [4:0]  cfg_fault_addr,

    // program memory write port
    input  wire        imem_we,
    input  wire [4:0]  imem_addr,
    input  wire [15:0] imem_wdata,

    // host side of the FIFOs
    input  wire        host_push,
    input  wire [15:0] host_push_data,
    input  wire        host_pop,
    output wire [15:0] host_pop_data,     // head of the RX FIFO
    output wire [2:0]  tx_level,
    output wire [2:0]  rx_level,

    // pins
    input  wire [31:0] pins_in,
    output reg  [31:0] out_val,
    output reg  [31:0] out_dir,

    // engine state, visible for testing
    output reg  [4:0]  pc,
    output reg  [15:0] x,
    output reg  [15:0] y,
    output reg  [15:0] osr,
    output reg  [4:0]  osr_count,
    output reg  [15:0] isr,
    output reg  [4:0]  isr_count,
    output reg  [4:0]  delay,
    output reg  [15:0] sw,
    output reg         sw_run
);

    // ------------------------------------------------------------------ helpers
    function [31:0] rotl32(input [31:0] v, input [4:0] s);
        rotl32 = (v << s) | (v >> (6'd32 - {1'b0, s}));
    endfunction

    function [31:0] rotr32(input [31:0] v, input [4:0] s);
        rotr32 = (v >> s) | (v << (6'd32 - {1'b0, s}));
    endfunction

    // write `count` bits of `data` into `r`, starting at pin `base` (wrapping at 32)
    function [31:0] wr_bits(input [31:0] r, input [4:0] base, input [4:0] count, input [15:0] data);
        reg [31:0] m;
        begin
            m = rotl32((32'd1 << count) - 32'd1, base);
            wr_bits = (r & ~m) | (rotl32({16'd0, data}, base) & m);
        end
    endfunction

    function [15:0] bitrev16(input [15:0] v);
        integer i;
        begin
            for (i = 0; i < 16; i = i + 1) bitrev16[i] = v[15 - i];
        end
    endfunction

    // ------------------------------------------------------------------ storage
    reg [15:0] imem [0:31];
    always @(posedge clk) if (imem_we) imem[imem_addr] <= imem_wdata;

    reg [31:0] sync1, sync2;        // 2 flip-flop synchroniser
    reg [15:0] div;                 // clock divider
    wire       tick = (div == 16'd0);

    reg [15:0] txm [0:3];           // TX FIFO: host -> engine
    reg [1:0]  tx_rd, tx_wr;
    reg [2:0]  tx_cnt;
    reg [15:0] rxm [0:3];           // RX FIFO: engine -> host
    reg [1:0]  rx_rd, rx_wr;
    reg [2:0]  rx_cnt;

    assign tx_level      = tx_cnt;
    assign rx_level      = rx_cnt;
    assign host_pop_data = rxm[rx_rd];
    wire   host_push_ok  = host_push && (tx_cnt != 3'd4);
    wire   host_pop_ok   = host_pop  && (rx_cnt != 3'd0);

    // ------------------------------------------------------------------ working values for one step
    // (combinational: every one is assigned at the top of the always @(*) block)
    reg [15:0] instr;
    reg [2:0]  op;
    reg [4:0]  mid;
    reg [7:0]  a;
    reg [2:0]  dbits;
    reg [4:0]  dly, sval_full, pidx;
    reg        sen, stall, do_jump, take;
    reg [4:0]  jaddr, n;
    reg [5:0]  sum6;
    reg [15:0] data, v, msk;
    reg [16:0] m17;
    reg [31:0] t32;
    reg        tx_pop_eng, rx_push_eng;
    reg [15:0] rx_push_data;
    // next state
    reg [4:0]  n_pc, n_osr_count, n_isr_count, n_delay;
    reg [15:0] n_x, n_y, n_osr, n_isr, n_sw;
    reg        n_sw_run;
    reg [31:0] n_out_val, n_out_dir;

    // ------------------------------------------------------------------ next-state logic (one step)
    always @(*) begin
        // ---- defaults: nothing changes
        n_pc = pc; n_x = x; n_y = y;
        n_osr = osr; n_osr_count = osr_count;
        n_isr = isr; n_isr_count = isr_count;
        n_delay = delay; n_sw = sw; n_sw_run = sw_run;
        n_out_val = out_val; n_out_dir = out_dir;
        tx_pop_eng = 0; rx_push_eng = 0; rx_push_data = 0;
        instr = imem[pc];
        op = instr[15:13]; mid = instr[12:8]; a = instr[7:0];
        dbits = 3'd5 - {1'b0, cfg_side_count} - {2'b0, cfg_side_opt};
        dly = mid & ((5'd1 << dbits) - 5'd1);
        sval_full = (mid >> dbits) & ((5'd1 << cfg_side_count) - 5'd1);
        sen = (cfg_side_count != 2'd0) && (!cfg_side_opt || mid[4]);
        stall = 0; do_jump = 0; jaddr = 0; take = 0;
        n = (a[3:0] == 4'd0) ? 5'd16 : {1'b0, a[3:0]};
        m17 = (17'd1 << n) - 17'd1;
        msk = m17[15:0];
        data = 0; v = 0; t32 = 0; sum6 = 0; pidx = 0;

        if (tick) begin
            if (sw_run) n_sw = (sw == 16'hFFFF) ? sw : sw + 16'd1;

            if (delay != 5'd0) begin
                n_delay = delay - 5'd1;
            end else begin
                case (op)
                3'd0: begin                                         // JMP
                    case (a[7:5])
                        3'd0: take = 1'b1;
                        3'd1: take = (x == 16'd0);
                        3'd2: begin take = (x != 16'd0); n_x = x - 16'd1; end
                        3'd3: take = (y == 16'd0);
                        3'd4: begin take = (y != 16'd0); n_y = y - 16'd1; end
                        3'd5: take = (x != y);
                        3'd6: take = sync2[cfg_jmp_pin];
                        default: take = (osr_count < 5'd16);
                    endcase
                    if (take) begin do_jump = 1'b1; jaddr = a[4:0]; end
                end
                3'd1: begin                                         // WAIT
                    pidx = a[5] ? (cfg_in_base + a[4:0]) : a[4:0];
                    if (sync2[pidx] != a[7]) begin
                        if (a[6] && y == 16'd0) begin
                            do_jump = 1'b1; jaddr = cfg_fault_addr;
                        end else begin
                            if (a[6]) n_y = y - 16'd1;
                            stall = 1'b1;
                        end
                    end
                end
                3'd2: begin                                         // IN
                    case (a[7:5])
                        3'd0: begin t32 = rotr32(sync2, cfg_in_base); data = t32[15:0]; end
                        3'd1: data = x;
                        3'd2: data = y;
                        3'd4: data = isr;
                        3'd5: data = osr;
                        3'd6: data = n_sw;
                        default: data = 16'd0;
                    endcase
                    data = data & msk;
                    if (cfg_in_right) begin
                        t32 = {data, isr} >> n;
                    end else begin
                        t32 = ({16'd0, isr} << n) | {16'd0, data};
                    end
                    n_isr = t32[15:0];
                    sum6 = {1'b0, isr_count} + {1'b0, n};
                    n_isr_count = (sum6 > 6'd16) ? 5'd16 : sum6[4:0];
                end
                3'd3: begin                                         // OUT
                    if (cfg_out_right) begin
                        data  = osr & msk;
                        n_osr = osr >> n;
                    end else begin
                        data  = (osr >> (5'd16 - n)) & msk;
                        n_osr = osr << n;
                    end
                    sum6 = {1'b0, osr_count} + {1'b0, n};
                    n_osr_count = (sum6 > 6'd16) ? 5'd16 : sum6[4:0];
                    case (a[7:5])
                        3'd0: n_out_val = wr_bits(out_val, cfg_out_base, n, data);
                        3'd1: n_x = data;
                        3'd2: n_y = data;
                        3'd4: n_out_dir = wr_bits(out_dir, cfg_out_base, n, data);
                        3'd5: begin do_jump = 1'b1; jaddr = data[4:0]; end
                        3'd6: begin n_isr = data; n_isr_count = n; end
                        default: ;
                    endcase
                end
                3'd4: begin                                         // PUSH / PULL
                    if (!a[7]) begin
                        if (a[6] && isr_count < 5'd16) begin
                        end else if (rx_cnt == 3'd4) begin
                            stall = a[5];
                        end else begin
                            rx_push_eng = 1'b1; rx_push_data = isr;
                            n_isr = 0; n_isr_count = 0;
                        end
                    end else begin
                        if (a[6] && osr_count < 5'd16) begin
                        end else if (tx_cnt == 3'd0) begin
                            if (a[5]) stall = 1'b1;
                            else begin n_osr = x; n_osr_count = 0; end
                        end else begin
                            tx_pop_eng = 1'b1;
                            n_osr = txm[tx_rd]; n_osr_count = 0;
                        end
                    end
                end
                3'd5: begin                                         // MOV
                    case (a[2:0])
                        3'd0: begin t32 = rotr32(sync2, cfg_in_base); v = t32[15:0]; end
                        3'd1: v = x;
                        3'd2: v = y;
                        3'd3: v = 16'd0;
                        3'd4: v = n_sw;
                        3'd5: v = {8'd0, 1'b0, rx_cnt, 1'b0, tx_cnt};
                        3'd6: v = isr;
                        default: v = osr;
                    endcase
                    if (a[4:3] == 2'd1)      v = ~v;
                    else if (a[4:3] == 2'd2) v = bitrev16(v);
                    case (a[7:5])
                        3'd0: n_out_val = wr_bits(out_val, cfg_out_base, cfg_out_count, v);
                        3'd1: n_x = v;
                        3'd2: n_y = v;
                        3'd5: begin do_jump = 1'b1; jaddr = v[4:0]; end
                        3'd6: begin n_isr = v; n_isr_count = 0; end
                        3'd7: begin n_osr = v; n_osr_count = 0; end
                        default: ;
                    endcase
                end
                3'd6: begin                                         // SET
                    case (a[7:5])
                        3'd0: n_out_val = wr_bits(out_val, cfg_set_base, {2'b0, cfg_set_count}, {11'd0, a[4:0]});
                        3'd1: n_x = {11'd0, a[4:0]};
                        3'd2: n_y = {11'd0, a[4:0]};
                        3'd4: n_out_dir = wr_bits(out_dir, cfg_set_base, {2'b0, cfg_set_count}, {11'd0, a[4:0]});
                        default: ;
                    endcase
                end
                default: begin                                      // TIME
                    case (a[7:5])
                        3'd0: begin n_sw = 16'd0; n_sw_run = 1'b1; end
                        3'd1: n_sw_run = 1'b0;
                        3'd2: n_x = n_sw;
                        3'd3: n_y = n_sw;
                        3'd4: begin n_isr = n_sw; n_isr_count = 5'd16; end
                        default: ;
                    endcase
                end
                endcase

                // side-set: on every executed step, stalled or not; wins over the instruction
                if (sen)
                    n_out_val = wr_bits(n_out_val, cfg_side_base, {3'b0, cfg_side_count}, {11'd0, sval_full});

                if (!stall) begin
                    n_delay = dly;
                    n_pc = do_jump ? jaddr : ((pc == cfg_wrap_top) ? cfg_wrap_bottom : pc + 5'd1);
                end
            end
        end
    end

    // ------------------------------------------------------------------ flip-flops
    always @(posedge clk) begin
        if (!rst_n) begin
            pc <= cfg_start;
            x <= 0; y <= 0;
            osr <= 0; osr_count <= 5'd16;
            isr <= 0; isr_count <= 0;
            delay <= 0; sw <= 0; sw_run <= 0;
            out_val <= 0; out_dir <= 0;
            div <= 0; sync1 <= 0; sync2 <= 0;
            tx_rd <= 0; tx_wr <= 0; tx_cnt <= 0;
            rx_rd <= 0; rx_wr <= 0; rx_cnt <= 0;
        end else begin
            // ---- registers
            pc <= n_pc; x <= n_x; y <= n_y;
            osr <= n_osr; osr_count <= n_osr_count;
            isr <= n_isr; isr_count <= n_isr_count;
            delay <= n_delay; sw <= n_sw; sw_run <= n_sw_run;
            out_val <= n_out_val; out_dir <= n_out_dir;
            div <= tick ? cfg_clkdiv : div - 16'd1;
            sync2 <= sync1; sync1 <= pins_in;

            // ---- FIFOs (host and engine can act in the same clock)
            if (host_push_ok) begin txm[tx_wr] <= host_push_data; tx_wr <= tx_wr + 2'd1; end
            if (tx_pop_eng)   tx_rd <= tx_rd + 2'd1;
            tx_cnt <= tx_cnt + {2'b0, host_push_ok} - {2'b0, tx_pop_eng};
            if (rx_push_eng)  begin rxm[rx_wr] <= rx_push_data; rx_wr <= rx_wr + 2'd1; end
            if (host_pop_ok)  rx_rd <= rx_rd + 2'd1;
            rx_cnt <= rx_cnt + {2'b0, rx_push_eng} - {2'b0, host_pop_ok};
        end
    end

endmodule
