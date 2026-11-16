// Colorlight i9 v7.2 bring-up: the module LED (D2, pin L2) toggles every 0.17 s (4x blink, to prove the LED is ours) from the 25 MHz oscillator (pin P3).
module blink_fast (input wire clk25, output wire led);
    reg [24:0] count = 0;
    always @(posedge clk25) count <= count + 1'b1;
    assign led = count[22];
endmodule
