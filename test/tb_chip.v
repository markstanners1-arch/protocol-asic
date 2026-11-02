// End-to-end test of the whole chip, driven only through the SPI host port (as a real host would).
// Engine A: UART transmitter on engine pin 0 (uio[0]), 40 clocks per bit.
// Engine B: measures the bit time of the first 'U' on the same pin, pushes it to its RX FIFO.
`timescale 1ns/1ps
`default_nettype none
module tb_chip;
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n = 0;
    reg cs_n = 1, sck = 0, mosi = 0;
    reg [4:0] ui_hi = 0;
    wire [7:0] uo_out, uio_out, uio_oe;
    // pins with pull-ups: a driven pin reads back what is driven, an undriven one reads high
    wire [7:0] uio_in = (uio_out & uio_oe) | ~uio_oe;
    protocol_chip dut (.ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out), .uio_in(uio_in),
                       .uio_out(uio_out), .uio_oe(uio_oe), .ena(1'b1), .clk(clk), .rst_n(rst_n));
    wire miso = uo_out[0];
    wire irq  = uo_out[1];

    localparam HALF = 8;               // SCK half period in chip clocks: SCK = clk/16
    integer LATE = 0;                  // +late=1: sample MISO at the falling edge, like the ESP32
    integer errors = 0;
    reg [15:0] init [0:169];

    task spi_bit(input b, output r);
        begin
            mosi = b; repeat (HALF) @(posedge clk);
            sck = 1; if (!LATE) r = miso; repeat (HALF) @(posedge clk);
            if (LATE) r = miso;
            sck = 0;
        end
    endtask
    task spi_begin(input [7:0] cmd);
        integer i; reg r;
        begin
            cs_n = 0; repeat (HALF) @(posedge clk);
            for (i = 7; i >= 0; i = i - 1) spi_bit(cmd[i], r);
        end
    endtask
    task spi_word(input [15:0] w, output [15:0] got);
        integer i; reg r;
        begin
            for (i = 15; i >= 0; i = i - 1) begin spi_bit(w[i], r); got[i] = r; end
        end
    endtask
    task spi_end; begin repeat (HALF) @(posedge clk); cs_n = 1; repeat (2 * HALF) @(posedge clk); end endtask

    task write_reg(input e, input [5:0] a, input [15:0] w);
        reg [15:0] d; begin spi_begin({1'b0, e, a}); spi_word(w, d); spi_end; end
    endtask
    task read_reg(input e, input [5:0] a, output [15:0] w);
        begin spi_begin({1'b1, e, a}); spi_word(16'd0, w); spi_end; end
    endtask
    task load_engine(input e, input integer base);
        integer i; reg [15:0] d;
        begin
            spi_begin({1'b0, e, 6'h00});                                  // program: one burst of 32 words
            for (i = 0; i < 32; i = i + 1) spi_word(init[base + i], d);
            spi_end;
            spi_begin({1'b0, e, 6'h21});                                  // settings: one burst 0x21-0x25
            for (i = 0; i < 5; i = i + 1) spi_word(init[64 + 5 * e + i], d);
            spi_end;
        end
    endtask
    task check(input [511:0] what, input [15:0] got, input [15:0] want);
        begin
            if (got !== want) begin $display("FAIL: %0s = %0d (0x%h), expected %0d", what, got, got, want); errors = errors + 1; end
            else $display("ok:   %0s = %0d", what, got);
        end
    endtask

    // ---- watch the UART line on uio[0] like a terminal would (40 clocks per bit)
    reg [8*16-1:0] text = 0; integer nchars = 0; integer b; reg [7:0] c;
    initial begin
        forever begin
            @(negedge uio_in[0]);
            repeat (20) @(posedge clk);
            if (uio_in[0] === 1'b0) begin
                for (b = 0; b < 8; b = b + 1) begin repeat (40) @(posedge clk); c[b] = uio_in[0]; end
                repeat (40) @(posedge clk);
                if (uio_in[0] !== 1'b1) begin $display("FAIL: bad stop bit"); errors = errors + 1; end
                text = {text[8*15-1:0], c}; nchars = nchars + 1;
            end
        end
    end

    reg [15:0] w, st;
    integer i;
    reg [7:0] msg [0:6];
    initial begin
        $readmemh("chip_init.hex", init);
        if (!$value$plusargs("late=%d", LATE)) LATE = 0;
        msg[0]="U"; msg[1]="H"; msg[2]="e"; msg[3]="l"; msg[4]="l"; msg[5]="o"; msg[6]="!";
        repeat (5) @(posedge clk); rst_n = 1; repeat (5) @(posedge clk);

        load_engine(1, 32);  write_reg(1, 6'h20, 1);      // B: measure, run
        load_engine(0, 0);   write_reg(0, 6'h20, 1);      // A: UART, run

        read_reg(0, 6'h21, w); check("A CLKDIV read back", w, 4);
        read_reg(0, 6'h28, st); check("A STATUS running bit", st[8], 1);

        // program writes while running must be ignored (would break the UART if not)
        write_reg(0, 6'h01, 16'hFFFF);

        // send the message, never overfilling the 4-word FIFO
        for (i = 0; i < 7; i = i + 1) begin
            read_reg(0, 6'h28, st);
            while (st[2:0] == 3'd4) read_reg(0, 6'h28, st);
            write_reg(0, 6'h26, {8'd0, msg[i]});
        end
        repeat (7 * 400 + 2000) @(posedge clk);

        if (text[8*7-1:0] === {"U","H","e","l","l","o","!"} && nchars == 7) $display("ok:   UART line read \"%0s\"", text[8*7-1:0]);
        else begin $display("FAIL: UART line read \"%0s\" (%0d chars)", text, nchars); errors = errors + 1; end

        check("IRQ (B has data)", {15'd0, irq}, 1);
        read_reg(1, 6'h28, st); check("B RX level before", st[6:4], 1);
        // a 2-word burst from B's RX FIFO: first word = the measurement, second = 0 (empty), and only one pop
        spi_begin({1'b1, 1'b1, 6'h27}); spi_word(0, w); check("B measured bit time (clocks)", w, 40);
        spi_word(0, w); check("second word of burst (FIFO empty)", w, 0); spi_end;
        read_reg(1, 6'h28, st); check("B RX level after", st[6:4], 0);
        check("IRQ after reading", {15'd0, irq}, 0);

        // stop B, load a program that pushes 7, 8, 9; then reads must pop exactly what they return
        write_reg(1, 6'h20, 0);
        begin : reload
            integer j; reg [15:0] d;
            spi_begin({1'b0, 1'b1, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[74 + j], d);
            spi_end;
        end
        write_reg(1, 6'h22, 16'h7C00);           // start 0, wrap_bottom 0, wrap_top 31
        write_reg(1, 6'h20, 1);
        repeat (200) @(posedge clk);
        read_reg(1, 6'h28, st); check("B RX level after pushing 3", st[6:4], 3);
        read_reg(1, 6'h27, w);  check("single read", w, 7);
        read_reg(1, 6'h28, st); check("RX level after 1 read", st[6:4], 2);
        spi_begin({1'b1, 1'b1, 6'h27}); spi_word(0, w); check("burst word 1", w, 8);
        spi_word(0, w); check("burst word 2", w, 9); spi_end;
        read_reg(1, 6'h28, st); check("RX level after burst", st[6:4], 0);

        // pin conflict: A drives uio[2] low, B drives it high; A must win; stopping A must release the pin
        write_reg(0, 6'h20, 0); write_reg(1, 6'h20, 0);
        begin : conflict
            integer j, e; reg [15:0] d;
            for (e = 0; e < 2; e = e + 1) begin
                spi_begin({1'b0, e[0], 6'h00});
                for (j = 0; j < 32; j = j + 1) spi_word(init[106 + 32 * e + j], d);
                spi_end;
                spi_begin({1'b0, e[0], 6'h21});                    // clkdiv 0, wrap 0..31, set_base 2, set_count 1
                spi_word(16'd0, d); spi_word(16'h7C00, d); spi_word(16'd2 << 10, d); spi_word(16'd1, d); spi_word(16'd0, d);
                spi_end;
            end
        end
        write_reg(1, 6'h20, 1); repeat (50) @(posedge clk);
        check("uio[2] with only B driving (high)", {15'd0, uio_oe[2] & uio_out[2]}, 1);
        write_reg(0, 6'h20, 1); repeat (50) @(posedge clk);
        check("uio[2] with both driving (A low wins)", {14'd0, uio_oe[2], uio_out[2]}, 2);
        write_reg(0, 6'h20, 0); repeat (50) @(posedge clk);
        check("uio[2] after stopping A (B high again)", {15'd0, uio_oe[2] & uio_out[2]}, 1);
        write_reg(1, 6'h20, 0); repeat (50) @(posedge clk);
        check("uio[2] after stopping both (released)", {15'd0, uio_oe[2]}, 0);

        if (errors == 0) $display("PASS: whole chip, end to end through the SPI host port");
        else $display("FAIL: %0d errors", errors);
        $finish;
    end
    initial begin #20_000_000; $display("FAIL: timeout"); $finish; end
endmodule
