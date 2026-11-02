// Display diagnostic: every segment pin of both digits flips together, ~0.7 s low, ~0.7 s high.
// LED 1 on = segment pins HIGH, LED 1 off = segment pins LOW. LED 4 = heartbeat.
`default_nettype none
module seg_test_top (input wire i_clk, output wire [3:0] o_led, output wire [6:0] o_seg1, output wire [6:0] o_seg2);
    reg [24:0] t = 0;
    always @(posedge i_clk) t <= t + 1'b1;
    wire phase = t[24];
    assign o_seg1 = {7{phase}};
    assign o_seg2 = {7{phase}};
    assign o_led = {t[22], 2'b00, phase};
endmodule
