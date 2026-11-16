// Self-checking test bench for uart_tx.
// A simple model receiver watches the line, samples each bit in its middle,
// and compares every received byte with what was sent. Prints PASS or FAIL.

`timescale 1ns/1ps
`default_nettype none

module tb_uart_tx;

    reg         clk = 0;
    reg         rst_n = 0;
    reg  [15:0] divisor;
    reg  [7:0]  data = 0;
    reg         start = 0;
    wire        tx, busy;

    uart_tx dut (.clk(clk), .rst_n(rst_n), .divisor(divisor), .data(data),
                 .start(start), .tx(tx), .busy(busy));

    always #50 clk = ~clk;   // 10 MHz clock

    integer errors = 0;
    integer sent = 0;
    integer received = 0;
    reg [7:0] expected [0:255];

    // ---- model receiver: waits for a falling edge, then samples mid-bit ----
    integer i;
    reg [7:0] rx;
    initial begin
        forever begin
            @(negedge tx);
            repeat ((divisor + 1) / 2) @(posedge clk);          // middle of start bit
            if (tx !== 1'b0) begin
                $display("FAIL: start bit not low at its middle"); errors = errors + 1;
            end
            for (i = 0; i < 8; i = i + 1) begin
                repeat (divisor + 1) @(posedge clk);
                rx[i] = tx;
            end
            repeat (divisor + 1) @(posedge clk);                 // middle of stop bit
            if (tx !== 1'b1) begin
                $display("FAIL: stop bit not high"); errors = errors + 1;
            end
            if (rx !== expected[received]) begin
                $display("FAIL: byte %0d got %02h expected %02h", received, rx, expected[received]);
                errors = errors + 1;
            end
            received = received + 1;
        end
    end

    // ---- send one byte and wait for the transmitter to finish ----
    task send(input [7:0] b);
        begin
            @(posedge clk); while (busy) @(posedge clk);
            expected[sent] = b; sent = sent + 1;
            data <= b; start <= 1; @(posedge clk); start <= 0;
        end
    endtask

    integer k;
    initial begin
        $dumpfile("uart_tx.vcd");
        $dumpvars(0, tb_uart_tx);

        divisor = 16'd86;                      // 115200 baud at 10 MHz
        repeat (5) @(posedge clk); rst_n = 1;

        send(8'h55); send(8'h00); send(8'hFF); send(8'hA5); send("H"); send("i");
        for (k = 0; k < 20; k = k + 1) send($random);

        @(posedge clk); while (busy) @(posedge clk);
        repeat (200) @(posedge clk);           // let the receiver finish the last byte
        divisor = 16'd3;                       // very fast: 4 clocks per bit
        for (k = 0; k < 20; k = k + 1) send($random);

        @(posedge clk); while (busy) @(posedge clk);
        repeat (200) @(posedge clk);

        if (received != sent) begin
            $display("FAIL: sent %0d bytes, received %0d", sent, received); errors = errors + 1;
        end
        if (errors == 0) $display("PASS: %0d bytes sent and received correctly", sent);
        else             $display("FAIL: %0d errors", errors);
        $finish;
    end

endmodule
