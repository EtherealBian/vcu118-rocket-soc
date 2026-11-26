# Read-only netlist checks on the UART pads used to upload payloads on J4.
# No timing exceptions, no design or board writes. Designed for Vivado 2024.2.
if {$argc != 2} {error {usage: inspect-board-uart.tcl routed.dcp fresh.tsv}}
lassign $argv dcp out
if {![file isfile $dcp] || [file exists $out]} {error {require a checkpoint and a fresh output file}}
set_param general.maxThreads 2
open_checkpoint $dcp
proc leaves {pin direction} {
 set n [get_nets -quiet -segments -of_objects [get_pins $pin]]; if {![llength $n]} {error "no net at $pin"}
 return [lsort -unique [get_property NAME [get_pins -quiet -leaf -of_objects $n -filter "DIRECTION == $direction"]]]
}
set f [open $out {WRONLY CREAT EXCL}]; fconfigure $f -translation lf
puts $f "signal\tendpoint\tref\tlocation\tbel\tclock\tinput_driver\tload_count"
set sys clk_out1_harnessSysPLL
foreach name {uart_rx_meta_reg uart_rx_sync_reg} {
 set c [get_cells -quiet $name]; if {[llength $c]!=1 || [get_property REF_NAME $c] ne "FDRE" || [get_property ASYNC_REG $c] ni {1 TRUE true} || [get_property INIT $c] ni {1'b1 1}} {error "unmarked, uninitialized or missing receiving FF: $name"}
 set clock [get_clocks -quiet -of_objects [get_pins $c/C]]; if {$clock ne $sys} {error "wrong clock $clock at $name"}
 set loc [get_property LOC $c]; set bel [get_property BEL $c]; if {$loc eq "" || $bel eq ""} {error "unplaced stage $c"}
 set drivers [leaves $c/D OUT]; set loads [leaves $c/Q IN]
 if {[llength $drivers]!=1 || ![llength $loads]} {error "unexpected connectivity at $c"}
 puts $f [join [list RX $c [get_property REF_NAME $c] $loc $bel $clock $drivers [llength $loads]] "\t"]
 if {$name eq "uart_rx_meta_reg"} {
  set meta $c; set buf [get_cells -of_objects [get_pins $drivers]]; set ref [get_property REF_NAME $buf]
  puts "UART_RX_INPUT_DRIVER=$drivers REF=$ref"
  if {$ref ni {IBUF IBUFCTRL INBUF} || $loads ne "uart_rx_sync_reg/D"} {error "non-input buffer at meta/D, or meta/Q has other loads"}
  # Resolve the *actual* package port feeding this primitive, not just its instance name.
  set starts [all_fanin -flat -startpoints_only -to [get_pins $c/D]]
  if {[lsort -unique [get_property NAME $starts]] ne "uart_rxd"} {error "first FF driven by unexpected startpoints: $starts"}
  set padloads [all_fanout -flat -endpoints_only -from [get_ports uart_rxd]]
  if {[lsort -unique [get_property NAME $padloads]] ne "$c/D"} {error "raw uart_rxd has other captures: $padloads"}
 } elseif {$drivers ne "$meta/Q"} {error "no direct meta-to-clean connection"}
}
set paths [get_timing_paths -from [get_pins $meta/C] -to [get_pins uart_rx_sync_reg/D] -max_paths 1]; if {[llength $paths]!=1} {error {no receiver stage timing path}}
set slack [get_property SLACK $paths]; set delay [get_property DATAPATH_DELAY $paths]; set levels [get_property LOGIC_LEVELS $paths]
if {$levels!=0 || $slack<0} {error "untimed/negative/non-direct receiver path: $slack $levels"}
puts "UART_RX_INTERSTAGE slack_ns=$slack data_ns=$delay levels=$levels"
set tx [all_fanin -flat -startpoints_only -to [get_ports uart_txd]]
if {[llength $tx]!=1} {error "unexpected TX launch $tx"}
set pin [get_property NAME $tx]; set c [get_cells -of_objects $tx]; set clk [get_clocks -quiet -of_objects [get_pins $c/C]]
if {![string match FD* [get_property REF_NAME $c]] || $clk ne $sys} {error "TX is not a single system-clock FF: $pin $clk"}
puts $f [join [list TX $pin [get_property REF_NAME $c] [get_property LOC $c] [get_property BEL $c] $clk - -] "\t"]
close $f; close_design
puts BOARD_UART_RX_CHAIN_AND_TX_LAUNCH_CONFIRMED
