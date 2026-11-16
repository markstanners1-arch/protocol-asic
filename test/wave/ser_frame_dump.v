// Waveform recording for watching the serialiser send an Ethernet frame, clock by clock, in GTKWave.
// A second top-level module beside tb_chip (Icarus elaborates both): it copies the interesting signals into plainly
// named wires and records only those, from the moment the bench starts pushing the frame until 200 clocks after the
// serialiser goes idle. Run: bash test/wave/run_ser_frame.sh, then open test/wave/ser_frame.gtkw in GTKWave.
`timescale 1ns/1ps
`default_nettype none
module wave;
    // the host port (the bench drives these)
    wire        clk        = tb_chip.clk;
    wire        cs_n       = tb_chip.cs_n;
    wire        sck        = tb_chip.sck;
    wire        mosi       = tb_chip.mosi;
    // engine A and its serialiser
    wire [4:0]  engine_pc  = tb_chip.dut.clu[0].u.eng_slot[0].e.pc;
    wire [6:0]  fifo_level = tb_chip.dut.clu[0].u.eng_slot[0].e.tx_level;
    wire [1:0]  phase      = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.phase;   // 0 fill, 1 data, 2 crc, 3 end
    wire        busy       = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.busy;
    wire [15:0] words_left = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.words;
    wire        fifo_pop   = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.tx_pop;
    wire [15:0] shift_reg  = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.sh;
    wire [4:0]  bit_count  = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.bitn;
    wire        half_bit   = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.half;
    wire        line       = tb_chip.dut.clu[0].u.eng_slot[0].e.with_ser.u_ser.line;
    wire [31:0] crc        = tb_chip.dut.clu[0].u.eng_slot[0].e.crc;
    // the pins: TD+ and TD- (engine pins 8 and 9 in this test)
    wire        td_plus    = tb_chip.uo_out[2];
    wire        td_minus   = tb_chip.uo_out[3];

    initial begin
        $dumpfile("../wave/ser_frame.vcd");   // run from test/build, where the chip test reads its program file
        $dumpvars(1, wave);
        $dumpoff;
        wait (tb_chip.eth_rec === 1'b1);
        $dumpon;
        wait (busy === 1'b1);
        wait (busy === 1'b0);
        repeat (200) @(posedge clk);
        $dumpoff;
    end
endmodule
