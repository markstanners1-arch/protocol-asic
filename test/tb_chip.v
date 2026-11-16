// End-to-end test of the whole chip, driven only through the SPI host port (as a real host would).
// Engine A: UART transmitter on engine pin 0 (uio[0]), 40 clocks per bit.
// Engine B: measures the bit time of the first 'U' on the same pin, pushes it to its RX FIFO.
// Then: FIFO reads, pin conflicts, the glitch filter, I2C (A master, B watching, a bench slave that ACKs), and the
// multi-engine additions of 3 Nov 2026 (any NENG): the ID register, the last engine alone, the priority chain, numbers past the last.
// Then the serialiser (ISA v0.3, 5 Nov 2026): engine A sends a minimum Ethernet frame on uo_out[2]/[3] (engine pins 8, 9) from a
// count and 34 words pushed through the port; the bench decodes the Manchester pair and checks every byte and the FCS.
`timescale 1ns/1ps
`default_nettype none
module tb_chip;
    parameter NENG = 3;                // engines in the chip under test (3 = ASIC and Cyclone; 2 = the kit): -P tb_chip.NENG=2
    parameter SER0 = 1;                // engine 0 has the serialiser (0 = the kit's default build: the serialiser checks
    parameter CRC  = 1;                //   become "its registers read 0"); CRC units present
    parameter TXDEPTH0 = 1024;         // engine 0's TX FIFO depth (1024 the ASIC, 64 the FPGA serialiser builds)
    localparam FDX_TX = (TXDEPTH0 == 64) ? 16 : TXDEPTH0 / 2;   // full duplex: the transmit ring
    reg clk = 0; always #5 clk = ~clk;
    reg rst_n = 0;
    reg cs_n = 1, sck = 0, mosi = 0;
    reg [4:0] ui_hi = 0;
    wire [7:0] uo_out, uio_out, uio_oe;
    // pins with pull-ups: a driven pin reads back what is driven, an undriven one reads high
    reg sda_slave_low = 0;             // the bench's I2C slave pulling SDA (uio[1]) low for an ACK
    reg scl_slave_low = 0;             // ... and stretching the clock (holding SCL, uio[0], low)
    wire [7:0] uio_in = ((uio_out & uio_oe) | ~uio_oe) & ~{6'd0, sda_slave_low, scl_slave_low};
    wire rx_pad;                       // the receive pin's pad; the bench's falling-edge flip-flop stands in for the latch
    reg  rx_fall = 0;
    always @(negedge clk) rx_fall <= rx_pad;
    reg  loopback = 0;                 // full-duplex test: a wire from TD+ (engine pin 8, uo_out[2]) to engine pin 16
    wire [4:0] ui_hi_eff = loopback ? {ui_hi[4:2], uo_out[2], ui_hi[0]} : ui_hi;
    protocol_chip #(.NENG(NENG), .SER0(SER0), .CRC(CRC), .TXDEPTH0(TXDEPTH0)) dut (.ui_in({ui_hi_eff, mosi, sck, cs_n}), .uo_out(uo_out), .uio_in(uio_in),
                       .uio_out(uio_out), .uio_oe(uio_oe), .ena(1'b1), .clk(clk), .rst_n(rst_n),
                       .rx_pad(rx_pad), .rx_fall(rx_fall));
    wire miso = uo_out[0];
    wire irq  = uo_out[1];

    localparam HALF = 8;               // SCK half period in chip clocks: SCK = clk/16
    integer LATE = 0;                  // +late=1: sample MISO at the falling edge, like the ESP32
    integer errors = 0;
    integer se; reg [5:0] sa; reg [15:0] sw_want;
    function [15:0] sweep_val(input integer e, input [5:0] a);
        sweep_val = 16'hA5C3 ^ (e * 16'h1357) ^ ({10'd0, a} * 16'h0B21);
    endfunction
    function [15:0] sweep_mask(input [5:0] a);
        case (a)
            6'h22, 6'h23, 6'h25: sweep_mask = 16'h7FFF;
            6'h24:               sweep_mask = 16'h3FFF;
            6'h2B:               sweep_mask = 16'h1E7F;   // [8:7] read the mode in force (transmit here)
            default:             sweep_mask = 16'hFFFF;
        endcase
    endfunction
    reg [15:0] init [0:298];

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

    // ---- record TD+ (uo_out[2]) on every clock the serialiser drives the pair (TD+ and TD- differ): at SERDIV 0 one sample
    //      is one half-bit. Stops when the pair goes idle again.
    reg        eth_rec = 0;  integer nrec = 0;  reg td_hist [0:2047];
    always @(posedge clk) begin
        if (eth_rec && uo_out[2] != uo_out[3] && nrec < 2048) begin td_hist[nrec] <= uo_out[2]; nrec <= nrec + 1; end
    end

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

        // isolation: engine A hangs on a WAIT that is never met (measure_pulse on engine pin 16, which nothing drives:
        // it reads 0, so "wait 1" at address 0 never completes); B and the last engine keep working; A is recovered
        // through the host alone, without touching the others.
        begin : isolation
            integer j, L; reg [15:0] d;
            L = NENG - 1;
            for (j = 0; j < NENG; j = j + 1) write_reg(j[2:0], 6'h20, 0);
            ui_hi = 0;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h00});                  // A: measure_pulse, in_base 16 (ui_in[4], held low)
            for (j = 0; j < 32; j = j + 1) spi_word(init[170 + j], d);
            spi_end;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h21});
            spi_word(16'd0, d); spi_word(16'd5 << 10, d); spi_word(16'd0, d); spi_word(16'd0, d); spi_word(16'd16, d);
            spi_end;
            spi_begin({1'b0, 3'd1, 6'd0, 6'h00});                  // B: push 7, 8, 9
            for (j = 0; j < 32; j = j + 1) spi_word(init[74 + j], d);
            spi_end;
            write_reg(1, 6'h22, 16'h7C00);
            if (NENG >= 3) begin                                   // last engine: UART transmitter on engine pin 0, 40 clocks/bit
                spi_begin({1'b0, L[2:0], 6'd0, 6'h00});
                for (j = 0; j < 32; j = j + 1) spi_word(init[j], d);
                spi_end;
                spi_begin({1'b0, L[2:0], 6'd0, 6'h21});
                for (j = 0; j < 5; j = j + 1) spi_word(init[64 + j], d);
                spi_end;
            end
            write_reg(0, 6'h20, 1); repeat (100) @(posedge clk);
            read_reg(0, 6'h28, st); check("A hung on its first WAIT (pc 0, running)", st[13:8], 6'b000001);
            write_reg(1, 6'h20, 1); repeat (200) @(posedge clk);
            read_reg(1, 6'h27, w); check("B works while A hangs (word 1)", w, 7);
            read_reg(1, 6'h27, w); check("B works while A hangs (word 2)", w, 8);
            if (NENG >= 3) begin
                uart_watch = 1; nchars = 0; text = 0;
                write_reg(L[2:0], 6'h20, 1);
                write_reg(L[2:0], 6'h26, 16'h55); write_reg(L[2:0], 6'h26, 16'h3C);
                repeat (1200) @(posedge clk);
                check("last engine sent 2 UART bytes while A hangs", nchars, 2);
                check("  the second byte", {8'd0, text[7:0]}, 16'h3C);
                uart_watch = 0;
            end
            read_reg(0, 6'h28, st); check("A still hung (pc 0)", st[13:8], 6'b000001);
            // recover A alone: stop, reload with push_789, start; B and the last engine untouched
            write_reg(0, 6'h20, 0);
            spi_begin({1'b0, 3'd0, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[74 + j], d);
            spi_end;
            write_reg(0, 6'h22, 16'h7C00);
            write_reg(0, 6'h20, 1); repeat (200) @(posedge clk);
            read_reg(0, 6'h27, w); check("A recovered: pushes 7", w, 7);
            read_reg(1, 6'h28, st); check("B still running, its last word still waiting", st[8], 1'b1);
            read_reg(1, 6'h27, w); check("B's word 3 intact", w, 9);
            if (NENG >= 3) begin
                read_reg(L[2:0], 6'h28, st); check("last engine still running", st[8], 1'b1);
            end
            for (j = 0; j < NENG; j = j + 1) write_reg(j[2:0], 6'h20, 0);
        end

        // cluster field, command bits [11:6] (5 Nov 2026): cluster 0 is the chip; any other number reads 0 and ignores writes
        begin : clusters
            reg [15:0] d;
            write_reg(0, 6'h21, 16'h1234);
            spi_begin({1'b0, 3'd0, 6'd1, 6'h21}); spi_word(16'h5555, d); spi_end;      // write CLKDIV via cluster 1
            read_reg(0, 6'h21, w); check("cluster 1 write ignored: A CLKDIV unchanged", w, 16'h1234);
            spi_begin({1'b1, 3'd0, 6'd1, 6'h21}); spi_word(16'd0, w); spi_end;         // read CLKDIV via cluster 1
            check("cluster 1 reads 0 (CLKDIV)", w, 0);
            spi_begin({1'b1, 3'd0, 6'd63, 6'h2A}); spi_word(16'd0, w); spi_end;        // read ID via cluster 63
            check("cluster 63 reads 0 (ID)", w, 0);
            spi_begin({1'b0, 3'd0, 6'd2, 6'h29}); spi_word(16'h00FF, d); spi_end;      // write FILTER via cluster 2
            read_reg(0, 6'h29, w); check("cluster 2 write ignored: FILTER unchanged", w, 0);
            read_reg(0, 6'h2A, w); check("cluster 0 still answers (ID)", w, 16'h0020 | NENG);
            write_reg(0, 6'h21, 0);
        end

        // serialiser (5 Nov 2026): engine A runs eth_tx.asm, TD+ = engine pin 8 (uo_out[2]), TD- = pin 9 (uo_out[3]).
        // Without CRC units (the ASIC build, 7 Nov 2026) the same frame goes out with the FCS sent by the host as the
        // last two FIFO words and SERCFG's CRC append off; the wire must carry the same 72 bytes.
        if (!SER0 || TXDEPTH0 < 64) begin : no_ser                // a build without the serialiser
            write_reg(0, 6'h2B, 16'h107F); write_reg(0, 6'h2C, 16'h1234); write_reg(0, 6'h2D, 16'hA001);
            read_reg(0, 6'h2B, w); check("A SERCFG (built without the serialiser: reads 0)", w, SER0 ? 16'h107F : 16'd0);
            read_reg(0, 6'h2D, w); check("A CRCPOLY lo (reads 0 without CRC units)", w, CRC ? 16'hA001 : 16'd0);
            read_reg(0, 6'h28, st); check("A STATUS serialiser bits 0", st[15:14], 2'b00);
        end else begin : ethernet
            integer j, k, nbits, nw; reg [15:0] d, sc; reg [7:0] gotb; reg bad;
            reg [15:0] fw [0:35];           // the frame as words: preamble + SFD, 60 bytes, low byte first (+ FCS: no CRC)
            reg [7:0]  want [0:71];         // what must appear on the wire: 68 bytes then the FCS acf725d4 (zlib.crc32)
            nw = CRC ? 34 : 36;             // words the host sends
            sc = CRC ? 16'h107F : 16'h106F; // SERCFG: CRC append (bit 4) only with the CRC unit
            fw[0] = 16'h5555; fw[1] = 16'h5555; fw[2] = 16'h5555; fw[3] = 16'hd555;
            fw[4] = 16'hffff; fw[5] = 16'hffff; fw[6] = 16'hffff; fw[7] = 16'h0002; fw[8] = 16'h0000; fw[9] = 16'h0100; fw[10] = 16'hb588;
            for (j = 0; j < 23; j = j + 1) begin gotb = 8'h30 + 2 * j[7:0]; fw[11 + j] = {gotb + 8'd1, gotb}; end   // payload 0x30 .. 0x5d
            fw[34] = 16'hf7ac; fw[35] = 16'hd425;                                 // the FCS as the host sends it
            for (j = 0; j < 34; j = j + 1) begin want[2 * j] = fw[j][7:0]; want[2 * j + 1] = fw[j][15:8]; end
            want[68] = 8'hac; want[69] = 8'hf7; want[70] = 8'h25; want[71] = 8'hd4;
            for (j = 0; j < NENG; j = j + 1) write_reg(j[2:0], 6'h20, 0);
            spi_begin({1'b0, 3'd0, 6'd0, 6'h00});
            for (j = 0; j < 32; j = j + 1) spi_word(init[266 + j], d);
            spi_end;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h21});                      // clkdiv 0, wrap, out_base 8 count 2 set_base 8, set_count 2 + out_right, incfg 0
            spi_word(16'd0, d); spi_word(init[298], d); spi_word(16'd8 | (16'd2 << 5) | (16'd8 << 10), d); spi_word(16'd2 | (16'd1 << 11), d); spi_word(16'd0, d);
            spi_end;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h2B});                      // SERCFG, SERDIV, CRCPOLY lo/hi, CRCINIT lo/hi in one burst
            spi_word(sc, d); spi_word(16'd0, d); spi_word(16'h8320, d); spi_word(16'hEDB8, d); spi_word(16'hFFFF, d); spi_word(16'hFFFF, d);
            spi_end;
            read_reg(0, 6'h2B, w); check("A SERCFG read back", w, sc);
            read_reg(0, 6'h2E, w); check("A CRCPOLY hi read back (0 without CRC units)", w, CRC ? 16'hEDB8 : 16'd0);
            write_reg(1, 6'h2B, 16'h107F); write_reg(1, 6'h2C, 16'h1234); write_reg(1, 6'h2D, 16'hA001);
            read_reg(1, 6'h2B, w); check("B SERCFG reads 0 (no serialiser)", w, 0);
            read_reg(1, 6'h2C, w); check("B SERDIV reads 0", w, 0);
            read_reg(1, 6'h2D, w); check("B CRCPOLY lo read back (0 without CRC units)", w, CRC ? 16'hA001 : 16'd0);
            read_reg(0, 6'h2B, w); check("A SERCFG untouched by B's write", w, sc);
            write_reg(0, 6'h20, 1); repeat (100) @(posedge clk);
            check("pair idle: TD+ and TD- driven low", {14'd0, uo_out[3:2]}, 0);
            read_reg(0, 6'h28, st); check("A STATUS: running, not busy, no underrun", {st[15:14], st[8]}, 3'b001);
            read_reg(0, 6'h33, w);  check("A SERSTAT: TX level 0", w, 0);
            nrec = 0; eth_rec = 1;
            spi_begin({1'b0, 3'd0, 6'd0, 6'h26});                      // the frame: count, then 34 words, one burst
            spi_word(nw[15:0], d);
            for (j = 0; j < nw; j = j + 1) spi_word(fw[j], d);
            spi_end;
            read_reg(0, 6'h28, st); check("A STATUS busy while the frame goes out", st[14], 1'b1);
            repeat (2000) @(posedge clk);
            eth_rec = 0;
            read_reg(0, 6'h28, st); check("A STATUS after the frame: not busy, no underrun, running", {st[15:14], st[8]}, 3'b001);
            read_reg(0, 6'h31, w);  check("A CRC lo after the frame (the FCS before complementing; 0 without CRC)", w, CRC ? 16'h0853 : 16'd0);
            read_reg(0, 6'h32, w);  check("A CRC hi", w, CRC ? 16'h2BDA : 16'd0);
            nbits = 36 * 16;            // 34 words + the 32-bit FCS, from the CRC unit or from the host
            check("half-bits on the wire: 2 per bit + 6 of TP_IDL", nrec, 2 * nbits + 6);
            bad = 0;
            for (j = 0; j < nbits && !bad; j = j + 1) begin
                if (td_hist[2 * j] == td_hist[2 * j + 1]) begin
                    $display("FAIL: bit %0d: both half-bits %0d (not Manchester)", j, td_hist[2 * j]); errors = errors + 1; bad = 1;
                end
            end
            for (j = 0; j < 72 && !bad; j = j + 1) begin
                for (k = 0; k < 8; k = k + 1) gotb[k] = td_hist[2 * (8 * j + k) + 1];
                if (gotb !== want[j]) begin
                    $display("FAIL: byte %0d on the wire = %h, expected %h", j, gotb, want[j]); errors = errors + 1; bad = 1;
                end
            end
            if (!bad) $display("ok:   all 72 bytes decoded from the pair: preamble, SFD, header, payload, FCS");
            for (j = 0; j < 6; j = j + 1) if (td_hist[2 * nbits + j] !== 1'b1) bad = 1;
            check("TP_IDL: the last 6 half-bits high", {15'd0, bad}, 0);
            // underrun: a count of TXDEPTH0 + 1 with TXDEPTH0 words supplied; the serialiser starts when the FIFO is full
            // and runs dry. With 1024 words, SERSTAT's level stops at 127 and SERLEVEL (0x38) gives it exactly.
            spi_begin({1'b0, 3'd0, 6'd0, 6'h26});
            spi_word(TXDEPTH0[15:0] + 16'd1, d);
            for (j = 0; j < (TXDEPTH0 > 127 ? 300 : TXDEPTH0); j = j + 1) spi_word(fw[j % 34], d);
            spi_end;
            if (TXDEPTH0 > 127) begin
                repeat (200) @(posedge clk);
                read_reg(0, 6'h33, w);  check("A SERSTAT with 300 words waiting: level saturated at 127, busy", w, 16'h017F);
                read_reg(0, 6'h38, w);  check("A SERLEVEL: exactly 300 words waiting", w, 16'd300);
                read_reg(0, 6'h28, st); check("A STATUS: level saturated at 7", {13'd0, st[2:0]}, 7);
                spi_begin({1'b0, 3'd0, 6'd0, 6'h26});
                for (j = 300; j < TXDEPTH0; j = j + 1) spi_word(fw[j % 34], d);
                spi_end;
            end
            repeat (TXDEPTH0 * 32 + 200) @(posedge clk);
            read_reg(0, 6'h28, st); check("A STATUS after all the words but one: underrun, not busy", st[15:14], 2'b10);
            read_reg(0, 6'h38, w);  check("A SERLEVEL: FIFO empty", w, 0);
            read_reg(0, 6'h33, w);  check("A SERSTAT: underrun bit, FIFO empty", w, 16'h0200);
            check("pair released after the underrun", {14'd0, uo_out[3:2]}, 0);
            spi_begin({1'b0, 3'd0, 6'd0, 6'h26}); spi_word(16'd1, d); spi_word(16'haaaa, d); spi_end;   // a one-word frame clears it
            repeat (200) @(posedge clk);
            read_reg(0, 6'h28, st); check("A STATUS after the next frame: flag cleared", st[15:14], 2'b00);

            // receive (8 Nov 2026): engine A switched to receive by a keyed SERCFG write, a frame driven onto engine pin
            // 16 (ui_in[4]) at half-bit 2 clocks with half-clock precision, read back through register 0x26
            write_reg(0, 6'h29, 16'h004F);                              // the filter ON (N=15, P=4: 256 clocks): receive
                                                                        // bypasses it, so the frame must still arrive
            write_reg(0, 6'h24, 16'd2 | (16'd1 << 11) | (16'd1 << 12));  // MISC: in_right too (Ethernet is LSB first)
            read_reg(0, 6'h2B, w); check("SERCFG [7]: transmit in force", w[7], 1'b0);
            write_reg(0, 6'h2B, sc | 16'h0080);                         // bit 7 without the key: no change
            read_reg(0, 6'h2B, w); check("SERCFG [7] after a write without the key: still transmit", w[7], 1'b0);
            write_reg(0, 6'h2B, sc | 16'hA080);                         // key 101 in [15:13], bit 7 = receive
            read_reg(0, 6'h2B, w); check("SERCFG [7] after the keyed write: receive in force", w[7], 1'b1);
            read_reg(0, 6'h2B, w); check("SERCFG's other bits kept", w & 16'h1F7F, sc & 16'h1F7F);
            read_reg(0, 6'h36, w); check("RXSTAT: receive mode, nothing yet", w, 16'h8000);
            read_reg(0, 6'h35, w); check("RXGAP default 6 half-clocks", w, 16'd6);
            write_reg(0, 6'h26, 16'h1234);                              // the host cannot fill the buffer in receive mode
            read_reg(0, 6'h33, w); check("receive mode: a host write to 0x26 refused (level 0)", w[6:0], 7'd0);
            write_reg(0, 6'h34, 16'd16 | 16'h0040 | 16'h0080);          // pin 16, both edges, arm
            read_reg(0, 6'h34, w); check("RXCFG read back (the arm bit is not kept)", w, 16'd16 | 16'h0040);
            @(posedge clk); #2;
            ui_hi[1] = 0; #200;
            // every odd bit's edges 5 ns late, so some edges are first seen by the falling-edge sample and some by the
            // rising-edge one: the two sample paths must line up to the half-clock for this frame to decode
            for (j = 0; j < 72; j = j + 1)
                for (k = 0; k < 8; k = k + 1) begin
                    ui_hi[1] = ~want[j][k]; #20;
                    ui_hi[1] =  want[j][k];
                    if (k % 2) #15; else #25;
                end
            ui_hi[1] = 1; #60; ui_hi[1] = 0;
            repeat (100) @(posedge clk);
            read_reg(0, 6'h36, w); check("RXSTAT after the frame: receive mode, 32 words, ready", w, 16'hA001);
            read_reg(0, 6'h39, w); check("RXWORDS: 32", w, 16'd32);
            read_reg(1, 6'h39, w); check("B RXWORDS reads 0 (no receiver)", w, 0);
            check("IRQ high: a frame is ready", {15'd0, irq}, 1);
            bad = 0;
            for (j = 0; j < 32; j = j + 1) begin
                read_reg(0, 6'h26, w);
                if (w !== {want[8 + 2 * j + 1], want[8 + 2 * j]}) begin
                    if (!bad) $display("FAIL: received word %0d = %h, expected %h", j, w, {want[8 + 2 * j + 1], want[8 + 2 * j]});
                    errors = errors + 1; bad = 1;
                end
            end
            if (!bad) $display("ok:   all 32 received words read back through 0x26: destination address to FCS");
            read_reg(0, 6'h26, w); check("0x26 with the buffer empty reads 0", w, 0);
            // a change while a frame is coming in is refused
            write_reg(0, 6'h34, 16'd16 | 16'h0040 | 16'h0080);          // arm again
            @(posedge clk); #2;
            for (j = 0; j < 4; j = j + 1)
                for (k = 0; k < 8; k = k + 1) begin
                    ui_hi[1] = ~want[j][k]; #20;
                    ui_hi[1] =  want[j][k]; #20;
                end
            fork
                begin
                    for (j = 4; j < 72; j = j + 1)
                        for (k = 0; k < 8; k = k + 1) begin
                            ui_hi[1] = ~want[j][k]; #20;
                            ui_hi[1] =  want[j][k]; #20;
                        end
                    ui_hi[1] = 1; #60; ui_hi[1] = 0;
                end
                begin
                    write_reg(0, 6'h2B, sc | 16'hA000);                 // keyed: back to transmit, mid-frame
                    read_reg(0, 6'h36, w); check("mid-frame keyed change: refused flag, still receive", {w[15], w[3]}, 2'b11);
                end
            join
            repeat (100) @(posedge clk);
            read_reg(0, 6'h36, w); check("the frame still arrives complete (ready, 32 words)", {w[15], w[14:8], w[0]}, {1'b1, 7'd32, 1'b1});
            write_reg(0, 6'h2B, sc | 16'hA000);                         // idle now: back to transmit
            read_reg(0, 6'h2B, w); check("idle: keyed change back to transmit", w[7], 1'b0);
            read_reg(0, 6'h36, w); check("RXSTAT after the change: all clear", w, 0);
            write_reg(0, 6'h29, 0);
            check("IRQ low again (the received frame was dropped with the buffer)", {15'd0, irq}, 0);

            // full duplex (8 Nov 2026): a loopback wire from TD+ to engine pin 16. Engine A sends the frame through its
            // 16-word ring with the hardware preamble (the host feeds words as the level allows) while its own receiver
            // catches it into the 48-word ring; the host reads the received words from 0x37. SERDIV 63 (a word every
            // 2048 clocks) so the bench's SPI host, a word per ~1100 clocks with its level check, keeps up.
            write_reg(0, 6'h2C, 16'd63);
            write_reg(0, 6'h35, 16'd192);                               // RXGAP: 3/4 bit = 96 clocks = 192 half-clocks
            write_reg(0, 6'h2B, (sc & 16'hE3FF) | 16'h0200 | 16'hA100);  // skip 0, hardware preamble, key, full duplex
            read_reg(0, 6'h2B, w); check("SERCFG [8:7] after the keyed write: full duplex in force", {14'd0, w[8:7]}, 2);
            check("SERCFG [9] hardware preamble kept", {15'd0, w[9]}, 1);
            read_reg(0, 6'h36, w); check("RXSTAT: the receiver on, nothing yet", w, 16'h8000);
            write_reg(0, 6'h34, 16'd16 | 16'h0040 | 16'h0080);          // pin 16, both edges, arm
            loopback = 1;
            nw = CRC ? 30 : 32;                                         // the body (+ the FCS when the host sends it)
            write_reg(0, 6'h26, nw[15:0]);                              // the count: the program pulls it and starts
            k = 0;
            for (j = 4; j < 4 + nw; j = j + 1) begin
                read_reg(0, 6'h33, w);
                while (w[6:0] >= FDX_TX) begin repeat (200) @(posedge clk); read_reg(0, 6'h33, w); end
                if (w[6:0] > k) k = w[6:0];
                write_reg(0, 6'h26, fw[j]);
            end
            check("full duplex: the transmit ring never reported above its size", {9'd0, k[6:0]} <= FDX_TX, 1);
            st = 16'h4000;
            for (j = 0; j < 400 && st[14]; j = j + 1) begin repeat (500) @(posedge clk); read_reg(0, 6'h28, st); end
            check("full duplex: frame sent, not busy, no underrun", {14'd0, st[15:14]}, 0);
            repeat (2000) @(posedge clk);
            read_reg(0, 6'h36, w); check("full duplex: RXSTAT ready, 32 words, receiver on", {w[15], w[14:8], w[0]}, {1'b1, 7'd32, 1'b1});
            read_reg(0, 6'h26, w); check("full duplex: 0x26 reads 0 (received words are at 0x37)", w, 0);
            bad = 0;
            for (j = 0; j < 32; j = j + 1) begin
                read_reg(0, 6'h37, w);
                if (w !== {want[8 + 2 * j + 1], want[8 + 2 * j]}) begin
                    if (!bad) $display("FAIL: full duplex received word %0d = %h, expected %h", j, w, {want[8 + 2 * j + 1], want[8 + 2 * j]});
                    errors = errors + 1; bad = 1;
                end
            end
            if (!bad) $display("ok:   full duplex: engine A sent the frame and received it back, all 32 words through 0x37");
            loopback = 0;
            write_reg(0, 6'h2B, sc | 16'hA000);                         // back to transmit (idle)
            read_reg(0, 6'h2B, w); check("back to transmit", {14'd0, w[8:7]}, 0);
            write_reg(0, 6'h2C, 16'd0);
            write_reg(0, 6'h20, 0);
        end

        // Register sweep: a different value in every setting register of every engine (and one slot past the
        // last), then every one read back, so a register crossed between engines or addresses shows up.
        for (se = 0; se <= NENG && se < 8; se = se + 1) write_reg(se, 6'h20, 0);
        for (se = 0; se <= NENG && se < 8; se = se + 1)
            for (sa = 6'h21; sa <= 6'h30; sa = sa + 1)
                if (sa <= 6'h25 || sa >= 6'h2B) write_reg(se, sa, sweep_val(se, sa));
        for (se = 0; se <= NENG && se < 8; se = se + 1)
            for (sa = 6'h21; sa <= 6'h30; sa = sa + 1)
                if (sa <= 6'h25 || sa >= 6'h2B) begin
                    read_reg(se, sa, w);
                    if (se >= NENG)                                   sw_want = 0;    // no engine in this slot
                    else if ((sa == 6'h2B || sa == 6'h2C) && (se != 0 || !SER0)) sw_want = 0;   // engine 0 only
                    else if (sa >= 6'h2D && !CRC)                     sw_want = 0;
                    else sw_want = sweep_val(se, sa) & sweep_mask(sa);
                    if (w !== sw_want) begin
                        $display("FAIL: sweep engine %0d register 0x%h = 0x%h, expected 0x%h", se, sa, w, sw_want);
                        errors = errors + 1;
                    end
                end
        $display("ok:   register sweep, %0d slots", (NENG < 8) ? NENG + 1 : 8);

        if (errors == 0) $display("PASS: whole chip, end to end through the SPI host port");
        else $display("FAIL: %0d errors", errors);
        $finish;
    end
    initial begin #20_000_000; $display("FAIL: timeout"); $finish; end
endmodule
