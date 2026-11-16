// The Go Board's proven SPI host-port test (fpga/go_board/spi_test_top.v) on the MachXO3L kit's J4 pins.
// 12 MHz clock here, so the SPI limit is 1.5 MHz. LEDs (low = lit): P16 = CS active, N15 = heartbeat.
`default_nettype none
module spi_test_mxo3 (input wire clk, input wire cs_n, input wire mosi, input wire sck, output wire miso, output wire [1:0] led);
    wire [3:0] l; wire [6:0] s1, s2;
    spi_test_top t (.i_clk(clk), .pmod_cs(cs_n), .pmod_mosi(mosi), .pmod_miso(miso), .pmod_sck(sck),
                    .o_led(l), .o_seg1(s1), .o_seg2(s2));
    assign led = ~{l[3], l[0]};      // N15 = heartbeat, P16 = CS active
endmodule
