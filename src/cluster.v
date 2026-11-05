// One cluster: NENG engines (populated slots, 1 to NSLOT) sharing a pin bank, with their setting registers,
// the pin mux ("lowest engine wins") and this cluster's slice of the host register file.
// The chip (src/chip.v) holds the host port, the input filter and the ID register and instantiates NCLUSTER of these.
// Spec: docs/core_design.md (hierarchy), docs/host_port.md (registers), docs/isa.md (engines).
//
// Host bus in (one cluster's view, already qualified by the chip with this cluster's number):
//   wr      one-clock pulse: write wdata to (eng, addr)
//   pop     one-clock pulse: the word at (eng, addr) has been sent; for the RX FIFO this pops it
//   eng     slot number 0..7; a slot past the last populated one ignores writes and reads 0
//   rdata   the register at (eng, addr), combinational; 0 for registers this cluster does not hold
// Pins: pins_in is the bank as every engine sees it (NPIN numbers); out_val/out_dir are the bank's
// outputs after arbitration between the engines.

`timescale 1ns/1ps
`default_nettype none

module cluster #(
    parameter NENG  = 3,                // engines populated, 1 to NSLOT
    parameter NSLOT = 4,                // engine slots the cluster is laid out for (the host's engine field spans 8)
    parameter NPIN  = 32                // pin numbers in the bank (an engine's pin fields are 5 bits)
) (
    input  wire            clk,
    input  wire            rst_n,
    // host register bus
    input  wire            wr,
    input  wire            pop,
    input  wire [2:0]      eng,
    input  wire [5:0]      addr,
    input  wire [15:0]     wdata,
    output reg  [15:0]     rdata,
    // pin bank
    input  wire [NPIN-1:0] pins_in,
    output reg  [NPIN-1:0] out_val,
    output reg  [NPIN-1:0] out_dir,
    output reg             irq         // some engine's RX FIFO holds data
);
    wire eng_ok = (eng < NENG);         // a slot past the last populated engine: writes ignored, reads 0

    // ------------------------------------------------------------ setting registers, one set per populated slot
    reg        run      [0:NENG-1];
    reg [15:0] r_clkdiv [0:NENG-1];
    reg [14:0] r_wrap   [0:NENG-1];
    reg [14:0] r_outcfg [0:NENG-1];
    reg [13:0] r_misc   [0:NENG-1];
    reg [14:0] r_incfg  [0:NENG-1];

    integer k;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (k = 0; k < NENG; k = k + 1) begin
                run[k] <= 1'b0; r_clkdiv[k] <= 0; r_wrap[k] <= 0; r_outcfg[k] <= 0; r_misc[k] <= 0; r_incfg[k] <= 0;
            end
        end else if (wr && eng_ok) case (addr)
            6'h20: run[eng]      <= wdata[0];
            6'h21: r_clkdiv[eng] <= wdata;
            6'h22: r_wrap[eng]   <= wdata[14:0];
            6'h23: r_outcfg[eng] <= wdata[14:0];
            6'h24: r_misc[eng]   <= wdata[13:0];
            6'h25: r_incfg[eng]  <= wdata[14:0];
            default: ;
        endcase
    end

    // ------------------------------------------------------------ the engines
    wire [NPIN-1:0] e_out_val [0:NENG-1];
    wire [NPIN-1:0] e_out_dir [0:NENG-1];
    wire [15:0] pop_data [0:NENG-1];
    wire [2:0]  txl [0:NENG-1], rxl [0:NENG-1];
    wire [4:0]  e_pc [0:NENG-1];

    genvar g;
    generate
        for (g = 0; g < NENG; g = g + 1) begin : eng_slot
            wire sel = (eng == g);
            wire [15:0] x_, y_, osr_, isr_, sw_;
            wire [4:0]  oc_, ic_, dl_;
            wire        swr_;
            engine e (
                .clk(clk), .rst_n(rst_n & run[g]),
                .cfg_clkdiv(r_clkdiv[g]),
                .cfg_start(r_wrap[g][4:0]), .cfg_wrap_bottom(r_wrap[g][9:5]), .cfg_wrap_top(r_wrap[g][14:10]),
                .cfg_out_base(r_outcfg[g][4:0]), .cfg_out_count(r_outcfg[g][9:5]), .cfg_set_base(r_outcfg[g][14:10]),
                .cfg_set_count(r_misc[g][2:0]), .cfg_side_base(r_misc[g][7:3]), .cfg_side_count(r_misc[g][9:8]),
                .cfg_side_opt(r_misc[g][10]), .cfg_out_right(r_misc[g][11]), .cfg_in_right(r_misc[g][12]),
                .cfg_side_dir(r_misc[g][13]),
                .cfg_in_base(r_incfg[g][4:0]), .cfg_jmp_pin(r_incfg[g][9:5]), .cfg_fault_addr(r_incfg[g][14:10]),
                // program words: only while this engine is stopped
                .imem_we(wr && sel && addr[5] == 1'b0 && !run[g]), .imem_addr(addr[4:0]), .imem_wdata(wdata),
                .host_push(wr && sel && addr == 6'h26), .host_push_data(wdata),
                .host_pop(pop && sel && addr == 6'h27), .host_pop_data(pop_data[g]),
                .tx_level(txl[g]), .rx_level(rxl[g]),
                .pins_in(pins_in), .out_val(e_out_val[g]), .out_dir(e_out_dir[g]),
                .pc(e_pc[g]), .x(x_), .y(y_), .osr(osr_), .osr_count(oc_), .isr(isr_), .isr_count(ic_),
                .delay(dl_), .sw(sw_), .sw_run(swr_));
        end
    endgenerate

    // ------------------------------------------------------------ host reads: the selected slot's registers
    reg [15:0] eng_rdata;
    always @(*) begin
        case (addr)
            6'h20: eng_rdata = {15'd0, run[eng]};
            6'h21: eng_rdata = r_clkdiv[eng];
            6'h22: eng_rdata = {1'b0, r_wrap[eng]};
            6'h23: eng_rdata = {1'b0, r_outcfg[eng]};
            6'h24: eng_rdata = {2'b0, r_misc[eng]};
            6'h25: eng_rdata = {1'b0, r_incfg[eng]};
            6'h27: eng_rdata = (rxl[eng] != 0) ? pop_data[eng] : 16'd0;
            6'h28: eng_rdata = {2'b0, e_pc[eng], run[eng], 1'b0, rxl[eng], 1'b0, txl[eng]};
            default: eng_rdata = 16'd0;
        endcase
        rdata = eng_ok ? eng_rdata : 16'd0;
    end

    // ------------------------------------------------------------ pin bank: the lowest engine driving a pin wins
    integer m;
    always @(*) begin
        out_dir = {NPIN{1'b0}}; out_val = {NPIN{1'b0}}; irq = 1'b0;
        for (m = NENG - 1; m >= 0; m = m - 1) begin          // highest first, so the lowest has the last word
            out_dir = out_dir | e_out_dir[m];
            out_val = (e_out_dir[m] & e_out_val[m]) | (~e_out_dir[m] & out_val);
            irq     = irq | (rxl[m] != 0);
        end
    end

    // NSLOT is the layout count; the decode above addresses slots by the 3-bit engine field, and slots
    // NENG..NSLOT-1 are unpopulated (absent to the host). An out-of-range NENG fails elaboration:
    generate if (NENG < 1 || NENG > NSLOT) begin : bad_neng
        cluster_NENG_must_be_1_to_NSLOT not_a_module ();
    end endgenerate

endmodule
