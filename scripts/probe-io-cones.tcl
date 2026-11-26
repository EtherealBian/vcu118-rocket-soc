# Identify the actual input endpoints and output startpoints; no changes to design.
if {$argc!=1} {error "usage: post-opt.dcp"}; open_checkpoint [lindex $argv 0]
foreach n {uart_ctsn uart_rtsn uart_rxd uart_txd sdio_spi_cs sdio_spi_dat_0 sdio_spi_dat_1 sdio_spi_dat_2 sdio_spi_dat_3 jtag_jtag_TCK jtag_jtag_TMS jtag_jtag_TDI jtag_jtag_TDO jtag_srst_n} {
 set p [get_ports -quiet $n];if {[llength $p]!=1} {puts "MISSING=$n";continue}; puts "PORT=$n DIR=[get_property DIRECTION $p]";
 foreach kind {in out} {if {$kind eq "in"} {set pts [all_fanout -quiet -flat -endpoints_only -from $p]} else {set pts [all_fanin -quiet -flat -startpoints_only -to $p]};set pins [filter -quiet $pts {CLASS == pin}];set cells [get_cells -quiet -of_objects $pins];puts "  $kind: cells=[llength $cells]"; foreach c [lrange $cells 0 5] {puts "    [get_property REF_NAME $c] [get_property NAME $c]"}}
}
puts PROBED_IO_CONES
