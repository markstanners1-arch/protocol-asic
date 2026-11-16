// Colorlight i9 v7.2 bring-up: the module LED (D2, pin L2) toggles every 0.67 s from the 25 MHz oscillator (pin P3).
module blink (input wire clk25, output wire led);
    reg [24:0] count = 0;
    always @(posedge clk25) count <= count + 1'b1;
    assign led = count[24];
endmodule
