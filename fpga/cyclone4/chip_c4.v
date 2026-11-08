// The whole chip (src/chip.v, unchanged) on a Cyclone IV E board (EP4CE6), second-opinion toolchain (Quartus).
// Board clock 50 MHz (the ASIC's own speed) -> SPI host port up to 6.25 MHz (clk/8).
// Pin locations live in chip_c4.qsf (3 Nov 2026: the black EP4CE6E22C8N core board, right-hand header 38-72).
// Same port list as fpga/machxo3/chip_mxo3.v, so the ESP32 wiring plan carries over.

`default_nettype none

module chip_c4 (
    input  wire       clk,          // 50 MHz
    input  wire       cs_n, sck, mosi,
    output wire       miso, irq,
    inout  wire [7:0] uio,
    output wire [5:0] uo_hi,        // uo_out[7:2]  engine pins 8-13
    input  wire [4:0] ui_hi,        // ui_in[7:3]   engine pins 15-19
    output wire [1:0] led           // [0] IRQ, [1] heartbeat (most boards light LEDs when driven low)
);
`ifdef SER_BUILD
    // Serialiser build (build.sh ser): engine 0 with the serialiser and the 64-word TX FIFO, as the ASIC, no CRC units,
    // SER_NENG engines; chip clock 40 MHz from the PLL (50 x 4 / 5), the rate 10 Mbit Manchester needs (SERDIV 1).
    wire cclk, locked;
    wire [4:0] pll_clks;
    altpll #(
        .intended_device_family("Cyclone IV E"), .lpm_type("altpll"), .operation_mode("NORMAL"), .pll_type("AUTO"),
        .inclk0_input_frequency(20000), .compensate_clock("CLK0"), .width_clock(5),
        .clk0_multiply_by(4), .clk0_divide_by(5), .clk0_duty_cycle(50), .clk0_phase_shift("0"),
        .port_inclk0("PORT_USED"), .port_clk0("PORT_USED"), .port_locked("PORT_USED"),
        .port_clk1("PORT_UNUSED"), .port_clk2("PORT_UNUSED"), .port_clk3("PORT_UNUSED"), .port_clk4("PORT_UNUSED")
    ) pll (.inclk({1'b0, clk}), .clk(pll_clks), .locked(locked));
    assign cclk = pll_clks[0];
    localparam NE = `SER_NENG, SER = 1, TXD = 64;
`else
    wire cclk = clk, locked = 1'b1;
    // three engines: fits at 98 % with Quartus set to optimise for area (four do not); built without the serialiser and the
    // CRC units (5 Nov 2026), as the MachXO3L kit, so the build is the one that fitted
    localparam NE = 3, SER = 0, TXD = 4;
`endif

    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge cclk) if (!rst_n && locked) por <= por + 1'b1;

    wire [7:0] uo_out, uio_out, uio_oe;
    protocol_chip #(.NENG(NE), .SER0(SER), .CRC(0), .TXDEPTH0(TXD)) chip (
        .ui_in({ui_hi, mosi, sck, cs_n}), .uo_out(uo_out),
        .uio_in(uio), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(cclk), .rst_n(rst_n));

    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : t
        assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
    end endgenerate

    assign miso  = uo_out[0];
    assign irq   = uo_out[1];
    assign uo_hi = uo_out[7:2];

    reg [25:0] beat = 0;
    always @(posedge cclk) beat <= beat + 1'b1;
    assign led = ~{beat[25], irq};
endmodule
