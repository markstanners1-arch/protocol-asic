// Switch-bounce meter on the Go Board: tests the chip's glitch filter (src/glitch_filter.v) on a real switch.
//
// Switch 1 is the switch under test. For every press and every release it sends one line over the
// USB serial port (115200 8N1), fields in hex (fpga/go_board/bounce_listen.ps1 turns them into plain English):
//   E L<level> R<raw edges> F<filtered edges> B<bounce us> D<filter delay us> M<setting>
//     raw edges      edges seen straight from the switch (bounces included)
//     filtered edges edges after the glitch filter (should be 1)
//     bounce us      time from the first raw edge to the last one
//     filter delay   time from the first raw edge to the filter's output changing
// Switch 2 steps the filter setting 0..5 (switch 2 is itself cleaned up by a ~21 ms filter) and sends
//   S L0 R0000 F0000 B0000 D0000 M<setting>
// Settings (25 MHz clock):  0 off  1 ~10 us  2 ~82 us  3 ~655 us  4 ~2.6 ms  5 ~10.5 ms
// LEDs: 1 = switch 1 raw, 2 = switch 1 filtered, 4 = heartbeat.

`default_nettype none

module bounce_top (
    input  wire       i_clk,
    input  wire [3:0] i_sw,
    output wire [3:0] o_led,
    output wire       o_uart_tx
);
    reg [7:0] por = 8'd0;
    wire rst_n = &por;
    always @(posedge i_clk) if (!rst_n) por <= por + 1'b1;

    // synchronise both switches
    reg [1:0] s0, s1;
    always @(posedge i_clk) begin s0 <= {s0[0], i_sw[0]}; s1 <= {s1[0], i_sw[1]}; end
    wire raw = s0[1];

    // filter setting presets (p, n)
    reg  [2:0] setting;
    reg  [3:0] fp, fn;
    always @(*) begin
        case (setting)
            3'd1: begin fp = 4'd4;  fn = 4'd15; end
            3'd2: begin fp = 4'd7;  fn = 4'd15; end
            3'd3: begin fp = 4'd10; fn = 4'd15; end
            3'd4: begin fp = 4'd12; fn = 4'd15; end
            3'd5: begin fp = 4'd14; fn = 4'd15; end
            default: begin fp = 4'd0; fn = 4'd0; end
        endcase
    end

    wire filt;
    glitch_filter #(.WIDTH(1)) f_test (.clk(i_clk), .rst_n(rst_n), .p(fp), .n(fn), .in(raw), .out(filt));
    wire sw2_clean;
    glitch_filter #(.WIDTH(1)) f_sw2 (.clk(i_clk), .rst_n(rst_n), .p(4'd15), .n(4'd15), .in(s1[1]), .out(sw2_clean));

    // microsecond tick
    reg [4:0] us_div;
    wire us_tick = (us_div == 5'd24);
    always @(posedge i_clk) us_div <= (!rst_n || us_tick) ? 5'd0 : us_div + 5'd1;

    // event measurement
    reg        raw_d, filt_d, sw2_d;
    reg        active;
    reg [15:0] now_us, quiet_us, raw_edges, filt_edges, last_edge_us, delay_us;
    reg        send_event, send_setting;
    always @(posedge i_clk) begin
        send_event <= 1'b0; send_setting <= 1'b0;
        raw_d <= raw; filt_d <= filt; sw2_d <= sw2_clean;
        if (!rst_n) begin
            active <= 1'b0; setting <= 3'd0; raw_d <= 1'b0; filt_d <= 1'b0; sw2_d <= 1'b0;
            now_us <= 0; quiet_us <= 0; raw_edges <= 0; filt_edges <= 0; last_edge_us <= 0; delay_us <= 0;
        end else begin
            if (sw2_clean && !sw2_d) begin
                setting <= (setting == 3'd5) ? 3'd0 : setting + 3'd1;
                send_setting <= 1'b1;
            end
            if (!active) begin
                if (raw != raw_d) begin                       // first edge of a press or release
                    active <= 1'b1; now_us <= 0; quiet_us <= 0;
                    raw_edges <= 16'd1; filt_edges <= 0; last_edge_us <= 0; delay_us <= 0;
                end
            end else begin
                if (us_tick) begin
                    if (now_us != 16'hFFFF) now_us <= now_us + 16'd1;
                    if (quiet_us != 16'hFFFF) quiet_us <= quiet_us + 16'd1;
                end
                if (raw != raw_d) begin
                    raw_edges <= raw_edges + 16'd1; last_edge_us <= now_us; quiet_us <= 0;
                end
                if (filt != filt_d) begin
                    filt_edges <= filt_edges + 16'd1;
                    if (filt_edges == 0) delay_us <= now_us;
                end
                if (quiet_us >= 16'd30000 && filt == raw) begin   // 30 ms of calm and the filter has caught up
                    active <= 1'b0; send_event <= 1'b1;
                end
            end
        end
    end

    // ---- message: "E L1 R0007 F0001 B019C D0290 M3\r\n" (31 bytes)
    reg  [4:0]  idx;
    reg         busy_msg;
    reg  [7:0]  kind;
    reg         m_level;
    reg  [15:0] m_r, m_f, m_b, m_d;
    reg  [2:0]  m_s;
    function [7:0] hx(input [3:0] v); hx = (v < 10) ? 8'h30 + v : 8'h37 + v; endfunction
    reg [7:0] ch;
    always @(*) begin
        case (idx)
            5'd0: ch = kind;                5'd1: ch = " ";  5'd2: ch = "L";  5'd3: ch = m_level ? "1" : "0";
            5'd4: ch = " ";  5'd5: ch = "R"; 5'd6: ch = hx(m_r[15:12]); 5'd7: ch = hx(m_r[11:8]); 5'd8: ch = hx(m_r[7:4]); 5'd9: ch = hx(m_r[3:0]);
            5'd10: ch = " "; 5'd11: ch = "F"; 5'd12: ch = hx(m_f[15:12]); 5'd13: ch = hx(m_f[11:8]); 5'd14: ch = hx(m_f[7:4]); 5'd15: ch = hx(m_f[3:0]);
            5'd16: ch = " "; 5'd17: ch = "B"; 5'd18: ch = hx(m_b[15:12]); 5'd19: ch = hx(m_b[11:8]); 5'd20: ch = hx(m_b[7:4]); 5'd21: ch = hx(m_b[3:0]);
            5'd22: ch = " "; 5'd23: ch = "D"; 5'd24: ch = hx(m_d[15:12]); 5'd25: ch = hx(m_d[11:8]); 5'd26: ch = hx(m_d[7:4]); 5'd27: ch = hx(m_d[3:0]);
            5'd28: ch = " "; 5'd29: ch = "M"; 5'd30: ch = hx({1'b0, m_s});
            default: ch = 8'h0A;
        endcase
    end
    // byte 31 is CR; then last_lf sends the LF
    wire [7:0] tx_byte = (idx == 5'd31) ? 8'h0D : ch;
    reg        last_lf;
    wire       tx_busy;
    reg        tx_start;
    uart_tx tx (.clk(i_clk), .rst_n(rst_n), .divisor(16'd216), .data(last_lf ? 8'h0A : tx_byte),
                .start(tx_start), .tx(o_uart_tx), .busy(tx_busy));

    always @(posedge i_clk) begin
        tx_start <= 1'b0;
        if (!rst_n) begin
            busy_msg <= 1'b0; idx <= 0; last_lf <= 1'b0; kind <= "E";
            m_level <= 0; m_r <= 0; m_f <= 0; m_b <= 0; m_d <= 0; m_s <= 0;
        end else if (!busy_msg) begin
            if (send_event || send_setting) begin
                busy_msg <= 1'b1; idx <= 0; last_lf <= 1'b0;
                kind <= send_event ? "E" : "S";
                m_level <= send_event ? raw : 1'b0;
                m_r <= send_event ? raw_edges : 16'd0;
                m_f <= send_event ? filt_edges : 16'd0;
                m_b <= send_event ? last_edge_us : 16'd0;
                m_d <= send_event ? delay_us : 16'd0;
                m_s <= setting;                   // already the new setting when send_setting fires
            end
        end else if (!tx_busy && !tx_start) begin
            tx_start <= 1'b1;
        end else if (tx_start) begin
            if (last_lf) busy_msg <= 1'b0;
            else if (idx == 5'd31) last_lf <= 1'b1;
            else idx <= idx + 5'd1;
        end
    end

    reg [23:0] beat = 0;
    always @(posedge i_clk) beat <= beat + 1'b1;
    assign o_led = {beat[23], 1'b0, filt, raw};
endmodule
