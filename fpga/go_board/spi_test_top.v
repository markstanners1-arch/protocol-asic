// Segment 1 bench test: the chip's real SPI host port (src/host_spi.v, unchanged) on the Go Board,
// driven by an ESP32 through the PMOD socket. Registers behind it are test stand-ins, not the engines.
//
//   PMOD 1 = CS, 2 = MOSI, 3 = MISO, 4 = SCK, 5 = GND     (SPI mode 0, max SCK = 25 MHz / 8 = 3.1 MHz by spec)
//
// Register map (same command format as docs/host_port.md):
//   0x00-0x07   scratch registers, read/write (a separate set of 8 for each engine-select bit: 16 in all)
//   0x26        write: push into a 4-word loop-back FIFO (dropped if full)
//   0x27        read:  pop from that FIFO (0 if empty)
//   0x28        read:  FIFO level
//   0x29        read:  ID 0xA5C3 (is it alive?)
//   0x2A        read:  number of 16-bit words written since power-up
// Display: last byte written, in hex. LED 1 = CS active, LED 2 = FIFO not empty, LED 4 = heartbeat.

`default_nettype none

module spi_test_top (
    input  wire       i_clk,
    input  wire       pmod_cs,      // PMOD 1
    input  wire       pmod_mosi,    // PMOD 2
    output wire       pmod_miso,    // PMOD 3
    input  wire       pmod_sck,     // PMOD 4
    output wire [3:0] o_led,
    output wire [6:0] o_seg1,       // tens digit, segments A..G, low = lit
    output wire [6:0] o_seg2        // units digit
);
    // power-on reset
    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge i_clk) if (!rst_n) por <= por + 1'b1;

    wire cs_n = pmod_cs, mosi = pmod_mosi, sck = pmod_sck;
    wire miso;
    assign pmod_miso = miso;

    wire        wr, rd, pop, eng;
    wire [5:0]  addr;
    wire [15:0] wdata;
    reg  [15:0] rdata;

    host_spi host (.clk(i_clk), .rst_n(rst_n), .cs_n(cs_n), .sck(sck), .mosi(mosi), .miso(miso),
                   .wr(wr), .rd(rd), .pop(pop), .eng(eng), .addr(addr), .wdata(wdata), .rdata(rdata));

    reg [15:0] scratch [0:15];
    reg [15:0] fifo [0:3];
    reg [1:0]  f_rd, f_wr;
    reg [2:0]  f_cnt;
    reg [15:0] nwrites;
    reg [7:0]  last_byte;

    wire push_ok = wr && addr == 6'h26 && f_cnt != 3'd4;
    wire pop_ok  = pop && addr == 6'h27 && f_cnt != 3'd0;

    integer i;
    always @(posedge i_clk) begin
        if (!rst_n) begin
            f_rd <= 0; f_wr <= 0; f_cnt <= 0; nwrites <= 0; last_byte <= 0;
            for (i = 0; i < 16; i = i + 1) scratch[i] <= 16'd0;
        end else begin
            if (wr) begin
                nwrites <= nwrites + 16'd1;
                last_byte <= wdata[7:0];
                if (addr[5:3] == 3'd0) scratch[{eng, addr[2:0]}] <= wdata;
            end
            if (push_ok) begin fifo[f_wr] <= wdata; f_wr <= f_wr + 2'd1; end
            if (pop_ok)  f_rd <= f_rd + 2'd1;
            f_cnt <= f_cnt + {2'b0, push_ok} - {2'b0, pop_ok};
        end
    end

    always @(*) begin
        if (addr[5:3] == 3'd0)  rdata = scratch[{eng, addr[2:0]}];
        else case (addr)
            6'h27:   rdata = (f_cnt != 0) ? fifo[f_rd] : 16'd0;
            6'h28:   rdata = {13'd0, f_cnt};
            6'h29:   rdata = 16'hA5C3;
            6'h2A:   rdata = nwrites;
            default: rdata = 16'd0;
        endcase
    end

    // display and LEDs
    function [6:0] hex7(input [3:0] h);     // segments G..A, 1 = lit
        case (h)
            4'h0: hex7 = 7'b0111111; 4'h1: hex7 = 7'b0000110; 4'h2: hex7 = 7'b1011011; 4'h3: hex7 = 7'b1001111;
            4'h4: hex7 = 7'b1100110; 4'h5: hex7 = 7'b1101101; 4'h6: hex7 = 7'b1111101; 4'h7: hex7 = 7'b0000111;
            4'h8: hex7 = 7'b1111111; 4'h9: hex7 = 7'b1101111; 4'hA: hex7 = 7'b1110111; 4'hB: hex7 = 7'b1111100;
            4'hC: hex7 = 7'b0111001; 4'hD: hex7 = 7'b1011110; 4'hE: hex7 = 7'b1111001; default: hex7 = 7'b1110001;
        endcase
    endfunction
    wire [6:0] s1 = hex7(last_byte[7:4]), s2 = hex7(last_byte[3:0]);
    assign o_seg1 = ~s1;
    assign o_seg2 = ~s2;

    reg [23:0] beat = 0;
    always @(posedge i_clk) beat <= beat + 1'b1;
    assign o_led = {beat[23], 1'b0, f_cnt != 0, !cs_n};

    wire _unused = &{rd, 1'b0};
endmodule
