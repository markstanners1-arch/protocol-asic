// First bench test on the Nandland Go Board.
// Sends "Hello from Gosforth Skies" over the board's USB serial port once a second
// (115200 baud, 8N1), using our uart_tx.v unchanged. LED 1 toggles with each message.
// Hold switch 1 to send continuously (a stress test: back-to-back bytes, no gaps).

`default_nettype none

module hello_top (
    input  wire       i_clk,     // 25 MHz
    input  wire [3:0] i_sw,      // push buttons, high when pressed
    output wire [3:0] o_led,
    output wire       o_uart_tx
);

    // Power-on reset: hold reset for the first 255 clocks (the board has no reset button)
    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge i_clk) if (!rst_n) por <= por + 1'b1;

    // Message ROM
    localparam LEN = 27;
    reg [7:0] msg [0:LEN-1];
    initial begin
        msg[0]="H"; msg[1]="e"; msg[2]="l"; msg[3]="l"; msg[4]="o"; msg[5]=" ";
        msg[6]="f"; msg[7]="r"; msg[8]="o"; msg[9]="m"; msg[10]=" ";
        msg[11]="G"; msg[12]="o"; msg[13]="s"; msg[14]="f"; msg[15]="o"; msg[16]="r";
        msg[17]="t"; msg[18]="h"; msg[19]=" "; msg[20]="S"; msg[21]="k"; msg[22]="i";
        msg[23]="e"; msg[24]="s"; msg[25]=8'h0D; msg[26]=8'h0A;
    end

    // 115200 baud at 25 MHz: 25e6/115200 = 217.0 clocks per bit -> divisor 216 (0.006% fast)
    wire busy;
    reg  start = 1'b0;
    reg  [4:0]  idx = 5'd0;
    reg  [24:0] tick = 25'd0;     // one-second timer
    reg         sending = 1'b0;
    reg         led = 1'b0;

    uart_tx tx (.clk(i_clk), .rst_n(rst_n), .divisor(16'd216), .data(msg[idx]),
                .start(start), .tx(o_uart_tx), .busy(busy));

    always @(posedge i_clk) begin
        start <= 1'b0;
        if (!rst_n) begin
            tick <= 0; sending <= 0; idx <= 0;
        end else begin
            tick <= (tick == 25'd24_999_999) ? 25'd0 : tick + 1'b1;
            if (!sending && (tick == 0 || i_sw[0])) begin
                sending <= 1'b1; idx <= 0; led <= ~led;
            end else if (sending && !busy && !start) begin
                if (idx == LEN) sending <= 1'b0;
                else begin start <= 1'b1; end
            end
            if (start) idx <= idx + 1'b1;
        end
    end

    assign o_led = {i_sw[0], 2'b00, led};

endmodule
