// Port list only, for synthesis: the real block is a hard macro placed by the layout tools.
(* blackbox *)
module RM_IHPSG13_1P_64x16_c2 (
    input  wire        A_CLK, A_MEN, A_WEN, A_REN, A_DLY,
    input  wire [5:0]  A_ADDR,
    input  wire [15:0] A_DIN,
    output wire [15:0] A_DOUT
);
endmodule
