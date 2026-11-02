// "Hello from Gosforth Skies" on the MachXO3L Starter Kit: 12 MHz clock, 115200 baud (12e6/115200 = 104.2 -> divisor 103, 0.2 % fast).
`default_nettype none
module hello_mxo3 (input wire clk, input wire [1:0] sw, output wire [1:0] led, output wire uart_tx);
    wire [3:0] l;
    hello_top #(.DIVISOR(16'd103), .SECOND(25'd11_999_999)) h (.i_clk(clk), .i_sw({2'b00, sw}), .o_led(l), .o_uart_tx(uart_tx));
    assign led = ~l[1:0];        // starter-kit LEDs light when driven low (to be confirmed on the board)
endmodule
