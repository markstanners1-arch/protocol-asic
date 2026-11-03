// End-to-end test of the whole chip, driven only through the SPI host port (as a real host would).
// Engine A: UART transmitter on engine pin 0 (uio[0]), 40 clocks per bit.
// Engine B: measures the bit time of the first 'U' on the same pin, pushes it to its RX FIFO.
// Then: FIFO reads, pin conflicts, the glitch filter, I2C (A master, B watching, a bench slave that ACKs), and the
// multi-engine additions of 3 Nov 2026 (any NENG): the ID register, the last engine alone, the priority chain, numbers past the last.
`timescale 1ns/1ps
`default_nettype none
module tb_chip;
    parameter NENG = 3;                // engines in the chip under test (3 = ASIC and Cyclone; 2 = the kit): -P tb_chip.NENG=2
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n = 0;
    reg cs_n = 1, sck = 0, mosi = 0;
    reg [4:0] ui_hi = 0;
    wire [7:0] uo_out, uio_out, uio_oe;
    // pins with pull-ups: a driven pin reads back what is driven, an undriven one reads high
    reg sda_slave_low = 0;             // the bench's I2C slave pulling SDA (uio[1]) low for an ACK
    reg scl_slave_low = 0;             // ... and stretching the clock (holding SCL, uio[0], low)
    wire [7:0] uio_in = ((uio_out & uio_oe) | ~uio_oe) & ~{6'd0, sda_slave_low, scl_slave_low};
    protocol_chip #(.NENG(NENG)) dut (.ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out), .uio_in(uio_in),
                       .uio_out(uio_out), .uio_oe(uio_oe), .ena(1'b1), .clk(clk), .rst_n(rst_n));
    wire miso = uo_out[0];
    wire irq  = uo_out[1];

    localparam HALF = 8;               // SCK half period in chip clocks: SCK = clk/16
    integer LATE = 0;                  // +late=1: sample MISO at the falling edge, like the ESP32
    integer errors = 0;
    reg [15:0] init [0:265];

    // ---- a minimal I2C slave on uio[0] (SCL) / uio[1] (SDA): after a START it ACKs every byte, until STOP,
    //      and stretches the clock (holds SCL low 90 clocks) after the 4th bit and after each ACK, as a slow slave might
    reg scl_q = 1, sda_q = 1, i2c_active = 0; integer i2c_bits = 0, stretch_left = 0;
    always @(posedge clk) begin
        if (stretch_left > 0) stretch_left <= stretch_left - 1;
        scl_slave_low <= (stretch_left > 1);
        scl_q <= uio_in[0]; sda_q <= uio_in[1];
        if (uio_in[0] && scl_q && sda_q && !uio_in[1]) begin i2c_active <= 1; i2c_bits <= 0; end         // START
        if (uio_in[0] && scl_q && !sda_q && uio_in[1]) begin i2c_active <= 0; sda_slave_low <= 0; end    // STOP
        if (i2c_active && !scl_q && uio_in[0]) i2c_bits <= i2c_bits + 1;                                 // SCL rose: a bit
        if (i2c_active && scl_q && !uio_in[0]) begin                                                     // SCL fell
            sda_slave_low <= (i2c_bits == 8);              // after the 8th bit: ACK, held through the 9th clock
            if (i2c_bits == 4 || i2c_bits == 9) stretch_left <= 90;    // mid-byte too: the master must really wait
            if (i2c_bits == 9) i2c_bits <= 0;
        end
    end

    task spi_bit(input b, output r);
        begin
            mosi = b; repeat (HALF) @(posedge clk);
            sck = 1; if (!LATE) r = miso; repeat (HALF) @(posedge clk);
            if (LATE) r = miso;
            sck = 0;
        end
    endtask
    task spi_begin(input [15:0] cmd);                            // {read, engine[2:0], 6'b0, register[5:0]}
        integer i; reg r;
        begin
            cs_n = 0; repeat (HALF) @(posedge clk);
            for (i = 15; i >= 0; i = i - 1) spi_bit(cmd[i], r);
        end
    endtask
    task spi_word(input [15:0] w, output [15:0] got);
        integer i; reg r;
        begin
            for (i = 15; i >= 0; i = i - 1) begin spi_bit(w[i], r); got[i] = r; end
        end
    endtask
    task spi_end; begin repeat (HALF) @(posedge clk); cs_n = 1; repeat (2 * HALF) @(posedge clk); end endtask

    task write_reg(input [2:0] e, input [5:0] a, input [15:0] w);
        reg [15:0] d; begin spi_begin({1'b0, e, 6'd0, a}); spi_word(w, d); spi_end; end
    endtask
    task read_reg(input [2:0] e, input [5:0] a, output [15:0] w);
        begin spi_begin({1'b1, e, 6'd0, a}); spi_word(16'd0, w); spi_end; end
    endtask
    task load_engine(input [2:0] e, input integer base);
        integer i; reg [15:0] d;
        begin
            spi_begin({1'b0, e, 6'd0, 6'h00});                            // program: one burst of 32 words
            for (i = 0; i < 32; i = i + 1) spi_word(init[base + i], d);
            spi_end;
            spi_begin({1'b0, e, 6'd0, 6'h21});                            // settings: one burst 0x21-0x25
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
    reg [8*16-1:0] text = 0; integer nchars = 0; integer b; reg [7:0] c; reg uart_watch = 1;   // off once the pin is reused
    initial begin
        forever begin
            @(negedge uio_in[0]);
            repeat (20) @(posedge clk);
            if (uart_watch && uio_in[0] === 1'b0) begin
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

        uart_watch = 0;
        check("IRQ (B has data)", {15'd0, irq}, 1);
        read_reg(1, 6'h28, st); check("B RX level before", st[6:4], 1);
        // a 2-word burst from B's RX FIFO: first word = the measurement, second = 0 (empty), and only one pop
        spi_begin({1'b1, 3'd1, 6'd0, 6'h27}); spi_word(0, w); check("B measured bit time (clocks)", w, 40);
        spi_word(0, w); check("second word of burst (FIFO empty)", w, 0); spi_end;
        read_reg(1, 6'h28, st); check("B RX level after", st[6:4], 0);
        check("IRQ after reading", {15'd0, irq}, 0);

        // stop B, load a program that pushes 7, 8, 9; then reads must pop exactly what they return
        write_reg(1, 6'h20, 0);
        begin : reload
            integer j; reg [15:0] d;
            spi_begin({1'b0, 3'd1, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[74 + j], d);
            spi_end;
        end
        write_reg(1, 6'h22, 16'h7C00);           // start 0, wrap_bottom 0, wrap_top 31
        write_reg(1, 6'h20, 1);
        repeat (200) @(posedge clk);
        read_reg(1, 6'h28, st); check("B RX level after pushing 3", st[6:4], 3);
        read_reg(1, 6'h27, w);  check("single read", w, 7);
        read_reg(1, 6'h28, st); check("RX level after 1 read", st[6:4], 2);
        spi_begin({1'b1, 3'd1, 6'd0, 6'h27}); spi_word(0, w); check("burst word 1", w, 8);
        spi_word(0, w); check("burst word 2", w, 9); spi_end;
        read_reg(1, 6'h28, st); check("RX level after burst", st[6:4], 0);

        // pin conflict: A drives uio[2] low, B drives it high; A must win; stopping A must release the pin
        write_reg(0, 6'h20, 0); write_reg(1, 6'h20, 0);
        begin : conflict
            integer j, e; reg [15:0] d;
            for (e = 0; e < 2; e = e + 1) begin
                spi_begin({1'b0, e[2:0], 6'd0, 6'h00});
                for (j = 0; j < 32; j = j + 1) spi_word(init[106 + 32 * e + j], d);
                spi_end;
                spi_begin({1'b0, e[2:0], 6'd0, 6'h21});                    // clkdiv 0, wrap 0..31, set_base 2, set_count 1
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

        // glitch filter: engine B times low pulses on engine pin 15 (ui_in[3]); a 30-clock glitch and a 200-clock pulse
        write_reg(0, 6'h20, 0); write_reg(1, 6'h20, 0);
        begin : filt
            integer j; reg [15:0] d;
            spi_begin({1'b0, 3'd1, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[170 + j], d);
            spi_end;
            spi_begin({1'b0, 3'd1, 6'd0, 6'h21});                    // clkdiv 0, wrap 0..5, outcfg 0, misc 0, in_base 15
            spi_word(16'd0, d); spi_word(16'd0 | (16'd0 << 5) | (16'd5 << 10), d); spi_word(16'd0, d); spi_word(16'd0, d); spi_word(16'd15, d);
            spi_end;
        end
        ui_hi[0] = 1;
        write_reg(0, 6'h29, 16'h0000);                          // filter: shortest
        read_reg(1, 6'h29, w); check("FILTER read back (off)", w, 0);
        write_reg(1, 6'h20, 1); repeat (50) @(posedge clk);
        ui_hi[0] = 0; repeat (30) @(posedge clk); ui_hi[0] = 1; repeat (100) @(posedge clk);
        read_reg(1, 6'h27, w); check("filter off: 30-clock glitch measured as", w, 30);
        ui_hi[0] = 0; repeat (200) @(posedge clk); ui_hi[0] = 1; repeat (100) @(posedge clk);
        read_reg(1, 6'h27, w); check("filter off: 200-clock pulse measured as", w, 200);
        write_reg(1, 6'h29, 16'h002F);                          // N = 15, P = 2: hold 16 ticks of 4 clocks = 64 clocks
        read_reg(0, 6'h29, w); check("FILTER read back (64-clock hold)", w, 16'h2F);
        ui_hi[0] = 0; repeat (30) @(posedge clk); ui_hi[0] = 1; repeat (300) @(posedge clk);
        read_reg(1, 6'h28, st); check("filter on: 30-clock glitch -> results waiting", st[6:4], 0);
        ui_hi[0] = 0; repeat (200) @(posedge clk); ui_hi[0] = 1; repeat (300) @(posedge clk);
        read_reg(1, 6'h27, w);
        if (w >= 196 && w <= 204) $display("ok:   filter on: 200-clock pulse measured as = %0d (within one prescale step)", w);
        else begin $display("FAIL: filter on: 200-clock pulse measured as %0d", w); errors = errors + 1; end

        // I2C: engine A is the master on uio[0] (SCL) / uio[1] (SDA), engine B watches the same two pins and
        // reports every byte with its ACK bit; the bench slave above ACKs. Checks the bus levels, A's ACK bits, B's bytes.
        write_reg(0, 6'h20, 0); write_reg(1, 6'h20, 0);
        begin : i2c
            integer j; reg [15:0] d;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[202 + j], d);
            spi_end;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h21});                    // A: clkdiv 1 (20 clocks/bit), wrap 0..18, out/in/set SDA (1),
            spi_word(16'd1, d); spi_word(16'd18 << 10, d); spi_word(16'd1 | (16'd1 << 5) | (16'd1 << 10), d); spi_word(16'h2501, d); spi_word(16'd1, d);
            spi_end;                                           //    set_count 1, side_base 0, side_count 1, side_opt, side_dir, MSB first
            spi_begin({1'b0, 3'd1, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[234 + j], d);
            spi_end;
            spi_begin({1'b0, 3'd1, 6'd0, 6'h21});                    // B: clkdiv 0, wrap 0..31, out_right, in_base 0, jmp_pin SDA
            spi_word(16'd0, d); spi_word(16'd31 << 10, d); spi_word(16'd0, d); spi_word(16'h0800, d); spi_word(16'd1 << 5, d);
            spi_end;
        end
        write_reg(0, 6'h29, 16'h0000);                          // filter back to its shortest (I2C edges are 20 clocks apart)
        write_reg(1, 6'h20, 1); write_reg(0, 6'h20, 1); repeat (50) @(posedge clk);
        read_reg(0, 6'h24, w); check("A MISC read back with side_dir", w, 16'h2501);
        check("I2C idle: SCL and SDA both released (open drain)", {14'd0, uio_oe[1:0]}, 0);
        spi_begin({1'b0, 3'd0, 6'd0, 6'h26});                        // 4 command words in one burst: START, 0xA0, 0x37, STOP
        spi_word(16'd12 << 11, w); spi_word((16'd3 << 11) | (16'hA0 << 3) | (16'd1 << 2), w);   // xfer: byte, ACK slot released
        spi_word((16'd3 << 11) | (16'h37 << 3) | (16'd1 << 2), w); spi_word(16'd15 << 11, w);
        spi_end;
        repeat (3000) @(posedge clk);
        read_reg(0, 6'h28, st); check("A RX level (two replies)", st[6:4], 2);
        read_reg(0, 6'h27, w); check("A: address byte as sent on the wire + ACK (0)", w, 16'hA0 << 1);
        read_reg(0, 6'h27, w); check("A: data byte as sent on the wire + ACK (0)", w, 16'h37 << 1);
        read_reg(1, 6'h28, st); check("B RX level (two bytes seen)", st[6:4], 2);
        read_reg(1, 6'h27, w); check("B saw address 0xA0 + ACK", w, 16'hA0 << 1);
        read_reg(1, 6'h27, w); check("B saw data 0x37 + ACK", w, 16'h37 << 1);
        check("I2C idle again: both released", {14'd0, uio_oe[1:0]}, 0);

        // four engines: ID register, engine C on its own (with the IRQ), the priority chain A > C > D, numbers past the last
        write_reg(0, 6'h20, 0); write_reg(1, 6'h20, 0);
        read_reg(0, 6'h2A, w); check("ID: spec version 2, number of engines", w, 16'h0020 | NENG);
        read_reg(5, 6'h2A, w); check("ID reads the same through any engine number", w, 16'h0020 | NENG);
        begin : more                                           // any engine count: the last engine (L = NENG-1) on its own
            integer j, e, L, M; reg [15:0] d;
            L = NENG - 1; M = NENG - 2;
            spi_begin({1'b0, L[2:0], 6'd0, 6'h00});                // L: push 7, 8, 9
            for (j = 0; j < 32; j = j + 1) spi_word(init[74 + j], d);
            spi_end;
            write_reg(L[2:0], 6'h22, 16'h7C00);
            write_reg(L[2:0], 6'h20, 1); repeat (200) @(posedge clk);
            read_reg(L[2:0], 6'h28, st); check("last engine: RX level after pushing 3", st[6:4], 3);
            check("IRQ (last engine has data)", {15'd0, irq}, 1);
            read_reg(L[2:0], 6'h27, w); check("last engine word 1", w, 7);
            read_reg(L[2:0], 6'h27, w); check("last engine word 2", w, 8);
            read_reg(L[2:0], 6'h27, w); check("last engine word 3", w, 9);
            check("IRQ after reading it", {15'd0, irq}, 0);
            write_reg(L[2:0], 6'h20, 0);
            if (NENG >= 3) begin                                   // priority chain on uio[2]: L low, M = L-1 high, then A low
                for (e = 0; e < NENG; e = e + 1) if (e == 0 || e == M || e == L) begin
                    spi_begin({1'b0, e[2:0], 6'd0, 6'h00});        // drive_low is init[106..], drive_high init[138..]
                    for (j = 0; j < 32; j = j + 1) spi_word(init[(e == M ? 138 : 106) + j], d);
                    spi_end;
                    spi_begin({1'b0, e[2:0], 6'd0, 6'h21});        // clkdiv 0, wrap 0..31, set_base 2, set_count 1
                    spi_word(16'd0, d); spi_word(16'h7C00, d); spi_word(16'd2 << 10, d); spi_word(16'd1, d); spi_word(16'd0, d);
                    spi_end;
                end
                write_reg(L[2:0], 6'h20, 1); repeat (50) @(posedge clk);
                check("uio[2] with only the last engine driving (low)", {14'd0, uio_oe[2], uio_out[2]}, 2);
                write_reg(M[2:0], 6'h20, 1); repeat (50) @(posedge clk);
                check("uio[2] with the last two driving (the lower one, high, wins)", {14'd0, uio_oe[2], uio_out[2]}, 3);
                write_reg(0, 6'h20, 1); repeat (50) @(posedge clk);
                check("uio[2] with A driving too (A low wins)", {14'd0, uio_oe[2], uio_out[2]}, 2);
                write_reg(0, 6'h20, 0); repeat (50) @(posedge clk);
                check("uio[2] after A stops (high again)", {14'd0, uio_oe[2], uio_out[2]}, 3);
                write_reg(M[2:0], 6'h20, 0); write_reg(L[2:0], 6'h20, 0); repeat (20) @(posedge clk);
                check("uio[2] released when all stop", {15'd0, uio_oe[2]}, 0);
            end
            // an engine number past the last: writes ignored, reads 0, nothing else disturbed
            e = NENG;
            write_reg(e[2:0], 6'h20, 1); write_reg(e[2:0], 6'h21, 16'h1234); repeat (20) @(posedge clk);
            read_reg(e[2:0], 6'h28, st); check("engine past the last: STATUS reads 0", st, 0);
            read_reg(e[2:0], 6'h21, w);  check("engine past the last: CLKDIV reads 0", w, 0);
            read_reg(1, 6'h21, w);       check("engine B's CLKDIV untouched by that write", w, 0);
            check("IRQ low with nothing waiting", {15'd0, irq}, 0);
        end

        if (errors == 0) $display("PASS: whole chip, end to end through the SPI host port");
        else $display("FAIL: %0d errors", errors);
        $finish;
    end
    initial begin #20_000_000; $display("FAIL: timeout"); $finish; end
endmodule
