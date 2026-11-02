// Plain UART transmitter: 8 data bits, no parity, 1 stop bit (8N1).
// Step one of the protocol emulator. A fixed-function block first,
// so we have something known-good to compare the programmable core against.
//
// Baud rate is set at run time: one bit lasts (divisor + 1) clock cycles.
// e.g. a 10 MHz clock and 115200 baud -> divisor = 10e6/115200 - 1 = 86.

`default_nettype none

module uart_tx (
    input  wire        clk,
    input  wire        rst_n,      // active-low reset (Tiny Tapeout convention)
    input  wire [15:0] divisor,    // clocks per bit, minus 1
    input  wire [7:0]  data,       // byte to send
    input  wire        start,      // pulse high for one clock to send `data`
    output reg         tx,         // serial line, idles high
    output wire        busy        // high while a byte is going out
);

    // Frame: start bit (0), 8 data bits LSB first, stop bit (1) = 10 bits
    reg [9:0]  shift;      // bits still to send, LSB goes out next
    reg [3:0]  bits_left;  // how many bits of the frame remain
    reg [15:0] count;      // clocks left in the current bit

    assign busy = (bits_left != 0);

    always @(posedge clk) begin
        if (!rst_n) begin
            tx        <= 1'b1;
            shift     <= 10'h3FF;
            bits_left <= 4'd0;
            count     <= 16'd0;
        end else if (!busy) begin
            tx <= 1'b1;
            if (start) begin
                // load the whole frame and put the start bit on the line now
                shift     <= {1'b1, data, 1'b0} >> 1;
                tx        <= 1'b0;
                bits_left <= 4'd10;
                count     <= divisor;
            end
        end else if (count != 0) begin
            count <= count - 1'b1;
        end else begin
            // current bit has lasted its full time: move to the next
            bits_left <= bits_left - 1'b1;
            if (bits_left != 1) begin
                tx    <= shift[0];
                shift <= {1'b1, shift[9:1]};
                count <= divisor;
            end else begin
                tx <= 1'b1;   // frame done, line back to idle
            end
        end
    end

endmodule
