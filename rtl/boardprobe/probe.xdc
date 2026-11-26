# VCU118 fabric differential SYSCLK (250 MHz), CP2105 Standard-side RX/TX.
set_property PACKAGE_PIN E12 [get_ports sys_clock_p]
set_property PACKAGE_PIN D12 [get_ports sys_clock_n]
set_property IOSTANDARD DIFF_SSTL12 [get_ports {sys_clock_p sys_clock_n}]
set_property PACKAGE_PIN AW25 [get_ports uart_rxd]
set_property PACKAGE_PIN BB21 [get_ports uart_txd]
set_property IOSTANDARD LVCMOS18 [get_ports {uart_rxd uart_txd}]
set_property DRIVE 8 [get_ports uart_txd]
set_property SLEW SLOW [get_ports uart_txd]
create_clock -name sys_clock -period 4.0 [get_ports sys_clock_p]
set_input_jitter [get_clocks sys_clock] 0.5
# Neither CP2105 nor MMCM LOCKED supplies a synchronous launch relationship.
# Cut only to the first synchronizer D, never between the two registers.
set_false_path -from [get_ports uart_rxd] -to [get_pins rx_meta_reg/D]
# LOCKED is a status output, not a Vivado timing startpoint. Build Tcl checks that it is the only driver.
set_false_path -to [get_pins lock_meta_reg/D]
# The off-chip UART samples start/data/stop asynchronously, not at 100 MHz.
set_false_path -from [get_pins protocol/tx_reg/C] -to [get_ports uart_txd]
# Match the board reference's inactive pin behavior. No Flash configuration writes.
set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
