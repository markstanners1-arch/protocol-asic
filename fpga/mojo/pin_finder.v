// Bench tool for the Mojo v3 + IO Shield: names the FPGA pin under a probe. Every header pin the chip build uses for a
// lead (host CS/SCK/MOSI, engine pins 0-7 and 15-19) is an input with a pull-up; touch one with a ground lead (through
// 220 R - 1 k) and the shield's display shows "P" and that pin's number, e.g. "P 51". "----" = nothing pulled low;
// the decimal points light if more than one pin is low. The Mojo's LEDs run a walking light to show it is loaded.
// Build: TOP=pin_finder bash fpga/mojo/build.sh load

`default_nettype none

module pin_finder (
    input  wire        clk,
    input  wire [15:0] probe,       // see pin_finder.ucf for the pin of each bit
    output wire [7:0]  led,
    output wire [23:0] io_led,
    output reg  [7:0]  io_seg,
    output reg  [3:0]  io_sel
);
    // FPGA pin number of each probe bit, as two decimal digits
    function [7:0] pin_bcd(input [3:0] k);
        case (k)
            4'd0:  pin_bcd = 8'h50;  4'd1:  pin_bcd = 8'h51;  4'd2:  pin_bcd = 8'h40;  4'd3:  pin_bcd = 8'h41;
            4'd4:  pin_bcd = 8'h34;  4'd5:  pin_bcd = 8'h35;  4'd6:  pin_bcd = 8'h32;  4'd7:  pin_bcd = 8'h33;
            4'd8:  pin_bcd = 8'h29;  4'd9:  pin_bcd = 8'h30;  4'd10: pin_bcd = 8'h27;  4'd11: pin_bcd = 8'h57;
            4'd12: pin_bcd = 8'h58;  4'd13: pin_bcd = 8'h66;  4'd14: pin_bcd = 8'h67;  default: pin_bcd = 8'h74;
        endcase
    endfunction
    function [6:0] seg7(input [3:0] d);             // gfedcba, 1 = lit
        case (d)
            4'd0: seg7 = 7'b0111111; 4'd1: seg7 = 7'b0000110; 4'd2: seg7 = 7'b1011011; 4'd3: seg7 = 7'b1001111;
            4'd4: seg7 = 7'b1100110; 4'd5: seg7 = 7'b1101101; 4'd6: seg7 = 7'b1111101; 4'd7: seg7 = 7'b0000111;
            4'd8: seg7 = 7'b1111111; 4'd9: seg7 = 7'b1100111; default: seg7 = 7'b0000000;
        endcase
    endfunction

    reg [15:0] s1 = 16'hFFFF, s2 = 16'hFFFF;        // two flip-flops on every probe input
    always @(posedge clk) begin s1 <= probe; s2 <= s1; end
    wire [15:0] low = ~s2;

    // lowest-numbered probe bit that is low, and whether more than one is
    reg [3:0] first; reg any, many; integer j;
    always @* begin
        first = 4'd0; any = 1'b0;
        for (j = 15; j >= 0; j = j - 1) if (low[j]) begin first = j; any = 1'b1; end
        many = any && ((low & (low - 16'd1)) != 16'd0);
    end
    wire [7:0] bcd = pin_bcd(first);

    reg [25:0] div = 0;
    always @(posedge clk) div <= div + 1'b1;
    wire [1:0] digit = div[17:16];                  // about 190 Hz per digit
    reg [6:0] s; reg dp;
    always @* begin
        dp = many;
        case (digit)
            2'd3:    s = any ? 7'b1110011 : 7'b1000000;              // leftmost: P, or a dash
            2'd2:    begin s = any ? 7'b0000000 : 7'b1000000; dp = 1'b0; end
            2'd1:    s = any ? seg7(bcd[7:4]) : 7'b1000000;
            default: s = any ? seg7(bcd[3:0]) : 7'b1000000;          // rightmost: units
        endcase
    end
    always @(posedge clk) begin
        io_seg <= ~{dp, s};                         // active low
        io_sel <= ~(4'b0001 << digit);
    end

    assign led = 8'b1 << div[25:23];
    assign io_led = 24'd0;
endmodule
