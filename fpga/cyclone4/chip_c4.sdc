# 50 MHz board oscillator. The host SPI and engine pins are asynchronous to the chip (synchronised inside).
create_clock -name clk -period 20.000 [get_ports clk]
derive_clock_uncertainty
set_false_path -from [get_ports {cs_n sck mosi uio[*] ui_hi[*]}]
set_false_path -to   [get_ports {miso irq uio[*] uo_hi[*] led[*]}]
